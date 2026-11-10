"""Detects whether -- and which version of -- an AWS SDK is declared
as a dependency in the scanned project's manifest files: boto3/
botocore for Python, aws-sdk / @aws-sdk/client-* for JS/TS,
aws-sdk-go(-v2) for Go, the AWS SDK for Java, aws-sdk-* gems for
Ruby, AWSSDK.* for C#, aws-sdk-*/aws-config crates for Rust, and
aws-sdk-cpp for C++.

Works like runtime.py: reads the same small set of manifest files
already used for --runtime, instead of scanning every source file's
imports. Faster, and answers the actual question ("is this declared
as a dependency") more directly.

A language with no AWS SDK detected just shows "-", same as --runtime.
"""

import re
from collections import namedtuple
from pathlib import Path

from src import manifest_utils as mu

# keyed by (resolved repo path, language)
_cache = {}

# sdk: name + version together, e.g. "aws-sdk-go-v2 v1.30.0"
# manifest: just the manifest's path relative to the repo root
AwsSdkInfo = namedtuple("AwsSdkInfo", ["sdk", "manifest"])


def _detect_python(repo_path):
    req = mu.find_manifest(repo_path, "requirements.txt")
    text = mu.read(req)
    version = mu.search(r"^\s*boto3\s*(?:[=<>~!]=?\s*([^\s,;#]+))?", text, re.MULTILINE)
    if version:
        return AwsSdkInfo(f"boto3 {version}", mu.label(repo_path, req))
    version = mu.search(r"^\s*botocore\s*(?:[=<>~!]=?\s*([^\s,;#]+))?", text, re.MULTILINE)
    if version:
        return AwsSdkInfo(f"botocore {version}", mu.label(repo_path, req))

    pyproject = mu.find_manifest(repo_path, "pyproject.toml")
    text = mu.read(pyproject)
    version = mu.search(r'"boto3(?:[=<>~!]=?)?([^"]*)"', text)
    if version is not None:
        return AwsSdkInfo(f"boto3 {version or '(unpinned)'}", mu.label(repo_path, pyproject))
    version = mu.search(r'^boto3\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if version:
        return AwsSdkInfo(f"boto3 {version}", mu.label(repo_path, pyproject))

    pipfile = mu.find_manifest(repo_path, "Pipfile")
    version = mu.search(r'^boto3\s*=\s*"([^"]+)"', mu.read(pipfile), re.MULTILINE)
    if version:
        return AwsSdkInfo(f"boto3 {version}", mu.label(repo_path, pipfile))

    return None


def _detect_js_ts(repo_path):
    package_json = mu.find_manifest(repo_path, "package.json")
    text = mu.read(package_json)

    # v3 is split across many @aws-sdk/client-* packages -- any one
    # present means v3; report the first match plus a count of others
    matches = list(re.finditer(r'"(@aws-sdk/(?:client|lib)-[\w-]+)"\s*:\s*"([^"]+)"', text or ""))
    if matches:
        name, version = matches[0].group(1), matches[0].group(2)
        extra = f" (+{len(matches) - 1} more @aws-sdk/* packages)" if len(matches) > 1 else ""
        return AwsSdkInfo(f"{name} {version}{extra}", mu.label(repo_path, package_json))

    version = mu.search(r'"aws-sdk"\s*:\s*"([^"]+)"', text)  # v2, older monolithic package
    if version:
        return AwsSdkInfo(f"aws-sdk {version}", mu.label(repo_path, package_json))

    return None


def _detect_go(repo_path):
    go_mod = mu.find_manifest(repo_path, "go.mod")
    text = mu.read(go_mod)

    # matches both "require x v1" (single-line) and just "x v1" inside a require() block
    version = mu.search(
        r"^\s*(?:require\s+)?github\.com/aws/aws-sdk-go-v2\s+(v[\d.]+\S*)", text, re.MULTILINE,
    )
    if version:
        return AwsSdkInfo(f"aws-sdk-go-v2 {version}", mu.label(repo_path, go_mod))

    version = mu.search(
        r"^\s*(?:require\s+)?github\.com/aws/aws-sdk-go\s+(v[\d.]+\S*)", text, re.MULTILINE,
    )
    if version:
        return AwsSdkInfo(f"aws-sdk-go {version}", mu.label(repo_path, go_mod))

    return None


def _detect_java(repo_path):
    pom = mu.find_manifest(repo_path, "pom.xml")
    text = mu.read(pom)
    if text:
        m = re.search(  # v2 groupId
            r"<groupId>\s*software\.amazon\.awssdk\s*</groupId>\s*"
            r"<artifactId>\s*([\w.-]+)\s*</artifactId>\s*"
            r"<version>\s*([^<\s]+)\s*</version>",
            text, re.DOTALL,
        )
        if m:
            return AwsSdkInfo(f"AWS SDK for Java v2 ({m.group(1)}) {m.group(2)}", mu.label(repo_path, pom))
        m = re.search(  # v1 groupId
            r"<groupId>\s*com\.amazonaws\s*</groupId>\s*"
            r"<artifactId>\s*([\w.-]+)\s*</artifactId>\s*"
            r"<version>\s*([^<\s]+)\s*</version>",
            text, re.DOTALL,
        )
        if m:
            return AwsSdkInfo(f"AWS SDK for Java v1 ({m.group(1)}) {m.group(2)}", mu.label(repo_path, pom))

    for gradle_file in ("build.gradle", "build.gradle.kts"):
        gradle = mu.find_manifest(repo_path, gradle_file)
        text = mu.read(gradle)
        version = mu.search(r"software\.amazon\.awssdk:[\w.-]+:([^\s'\"]+)", text)
        if version:
            return AwsSdkInfo(f"AWS SDK for Java v2 {version}", mu.label(repo_path, gradle))
        version = mu.search(r"com\.amazonaws:aws-java-sdk[\w.-]*:([^\s'\"]+)", text)
        if version:
            return AwsSdkInfo(f"AWS SDK for Java v1 {version}", mu.label(repo_path, gradle))

    return None


def _detect_ruby(repo_path):
    gemfile = mu.find_manifest(repo_path, "Gemfile")
    text = mu.read(gemfile)
    m = re.search(r'gem\s+["\'](\baws-sdk[\w-]*)["\'](?:\s*,\s*["\']([^"\']+)["\'])?', text or "")
    if m:
        version = m.group(2) or "(unpinned)"
        return AwsSdkInfo(f"{m.group(1)} {version}", mu.label(repo_path, gemfile))
    return None


def _detect_dotnet(repo_path):
    try:
        candidates = [p for p in repo_path.glob("**/*.csproj") if p.is_file()]
    except (OSError, ValueError):
        candidates = []
    candidates = [
        p for p in candidates
        if not any(part in mu.NOISE_DIRS for part in p.relative_to(repo_path).parts[:-1])
    ]
    candidates.sort(key=lambda p: len(p.relative_to(repo_path).parts))
    for csproj in candidates:
        text = mu.read(csproj)
        m = re.search(r'<PackageReference\s+Include="(AWSSDK\.[\w.]+)"\s+Version="([^"]+)"', text or "")
        if m:
            return AwsSdkInfo(f"{m.group(1)} {m.group(2)}", mu.label(repo_path, csproj))
    return None


def _detect_rust(repo_path):
    cargo_toml = mu.find_manifest(repo_path, "Cargo.toml")
    text = mu.read(cargo_toml)
    m = re.search(r'^(aws-(?:config|sdk-[\w-]+))\s*=\s*(?:"([^"]+)"|\{[^}]*version\s*=\s*"([^"]+)")',
                   text or "", re.MULTILINE)
    if m:
        version = m.group(2) or m.group(3) or "(unpinned)"
        return AwsSdkInfo(f"{m.group(1)} {version}", mu.label(repo_path, cargo_toml))
    return None


def _detect_cpp(repo_path):
    cmake = mu.find_manifest(repo_path, "CMakeLists.txt")
    text = mu.read(cmake)
    if text and re.search(r"aws-sdk-cpp|AWSSDK::", text):
        return AwsSdkInfo("aws-sdk-cpp", mu.label(repo_path, cmake))
    return None


_DETECTORS = {
    "Python": _detect_python,
    "JavaScript": _detect_js_ts,
    "TypeScript": _detect_js_ts,
    "Go": _detect_go,
    "Java": _detect_java,
    "Kotlin": _detect_java,
    "Ruby": _detect_ruby,
    "C#": _detect_dotnet,
    "F#": _detect_dotnet,
    "Rust": _detect_rust,
    "C++": _detect_cpp,
}


def detect_aws_sdk(repo_path, language):
    """AwsSdkInfo(sdk, manifest) for `language` in `repo_path`, or
    None if there's nothing to detect. Cached per (repo, language).
    """
    resolved = Path(repo_path).expanduser().resolve()
    key = (str(resolved), language)
    if key in _cache:
        return _cache[key]

    detector = _DETECTORS.get(language)
    if detector is None:
        _cache[key] = None
        return None

    try:
        result = detector(resolved)
    except Exception:
        result = None

    _cache[key] = result
    return result


def detect_aws_sdks(repo_path, languages):
    """{language: AwsSdkInfo_or_None} for every language given."""
    return {lang: detect_aws_sdk(repo_path, lang) for lang in languages}
