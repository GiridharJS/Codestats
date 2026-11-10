"""Detects each language's DECLARED runtime/version requirement by
reading the scanned project's own manifest files -- pom.xml or
build.gradle for Java, package.json/.nvmrc for JavaScript/TypeScript,
pyproject.toml/setup.cfg/.python-version for Python, go.mod for Go,
Gemfile/.ruby-version for Ruby, Cargo.toml/rust-toolchain for Rust,
CMakeLists.txt for C/C++, DESCRIPTION/renv.lock for R,
*.csproj/global.json for C#/F#, and (as a last-resort fallback for
every language above) an asdf/mise-style .tool-versions file.

This is a property of the REPOSITORY being scanned, not the machine
running codestats: two people scanning the identical repo on two
different machines get the identical answer here, which is the point
-- it answers "what version does this project say it needs to run",
not "what happens to be installed on PATH here, right now" (which is
what a machine-probing implementation would answer, and which makes
results non-reproducible across machines/CI runners).

`detect_runtime`/`detect_runtimes` check each manifest filename
directly at the root of the scanned path first (the common case). If
it isn't there -- because codestats was pointed at a parent folder, a
monorepo root, etc -- detection falls back to a recursive search and
uses the shallowest match, skipping common noise dirs (node_modules,
vendor, build output, VCS metadata) so a dependency's manifest isn't
picked up instead of the project's own.

That's right for "what's the ONE runtime for language X" but can hide
real info in a monorepo with different sub-projects declaring
different versions of the same language. find_project_roots is the
answer to that: finds every project root in the tree, not just one.

Missing manifests, unreadable files, missing fields are all handled
gracefully -- a language with no declared requirement just shows "-".
"""

import re
from pathlib import Path

from src import manifest_utils as _mu

# Cache keyed by (resolved repo path, language): a repo's declared
# requirements don't change mid-run, and re-reading/re-parsing
# manifest files is unnecessary work if the report is regenerated
# more than once in a single invocation.
_cache = {}

# These four are the actual manifest-finding/reading engine, shared
# with aws_sdk.py (see manifest_utils.py's module docstring for why)
# -- aliased under their original names here so every call site below
# doesn't need touching.
_NOISE_DIRS = _mu.NOISE_DIRS
_read = _mu.read
_find_manifest = _mu.find_manifest
_label = _mu.label
_search = _mu.search


# For project-root discovery (see find_project_roots): the manifest
# filename(s) that mark a directory as a project root for a given
# language. Order doesn't matter here -- ANY of these being present in
# a directory marks it as a root for that language.
_PROJECT_MANIFEST_FILENAMES = {
    "Java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "Kotlin": ["build.gradle.kts", "build.gradle", "pom.xml"],
    "Python": ["pyproject.toml", "setup.py", "setup.cfg", "Pipfile"],
    "JavaScript": ["package.json"],
    "TypeScript": ["package.json"],
    "Go": ["go.mod"],
    "Ruby": ["Gemfile"],
    "Rust": ["Cargo.toml"],
    "C#": ["*.csproj", "*.sln"],
    "F#": ["*.csproj", "*.sln"],
    "C": ["CMakeLists.txt"],
    "C++": ["CMakeLists.txt"],
    "R": ["DESCRIPTION"],
}


def _keep_only_outermost(paths):
    """Given an iterable of Path objects, drop any path that has
    another path in the same set as an ancestor -- keeping only the
    "outermost" entries. Sorting shallowest-first and checking each
    candidate against what's already been kept is enough: once a
    shallow root is kept, nothing deeper under it can ever be kept
    too, so there's no need to also check in the other direction.
    """
    ordered = sorted(paths, key=lambda p: len(p.parts))
    kept = []
    for p in ordered:
        if not any(k == p or k in p.parents for k in kept):
            kept.append(p)
    return kept


def find_project_roots(repo_path, detected_languages=None, max_roots=None):
    """Scan the whole repo tree for known per-language manifests, one
    entry per distinct project root -- not just the single shallowest
    match detect_runtime alone settles for. Makes a monorepo visible:
    services/api/pom.xml (Java 17) and services/legacy/build.gradle
    (Java 8) show up as two separate Java projects instead of
    collapsing into whichever's shallowest.

    Only the outermost manifest per subtree/language is reported --
    nested manifests belonging to test fixtures, vendored modules,
    etc get folded into their parent project rather than listed
    separately (golang/go alone has 20+ go.mod files scattered
    through test data; without this it'd flood the output). A
    different language's manifest nested inside still gets its own
    entry though.

    `detected_languages` (usually the scan's summary.keys()) filters
    to languages actually found in the scanned source -- otherwise a
    bare pom.xml/build.gradle (valid for both Java and Kotlin) would
    give every Java project a spurious Kotlin entry too.

    `max_roots` caps how many are returned, shallowest first.

    Returns a list of dicts, shallowest-root-first:
        {"root": "services/api", "languages": {"Java": "Java 17 (declared in pom.xml)"}}
    """
    resolved = Path(repo_path).expanduser().resolve()

    # language -> {project_dir: manifest_filename}, collected BEFORE
    # any outermost-filtering so every candidate is still available
    # when deciding which ones are nested inside another.
    candidates_by_language = {}

    for language, filenames in _PROJECT_MANIFEST_FILENAMES.items():
        if detected_languages is not None and language not in detected_languages:
            continue
        found = {}
        for filename in filenames:
            try:
                matches = [p for p in resolved.glob(f"**/{filename}") if p.is_file()]
            except (OSError, ValueError):
                continue
            for manifest_path in matches:
                rel_parts = manifest_path.relative_to(resolved).parts[:-1]
                if any(part in _NOISE_DIRS for part in rel_parts):
                    continue
                found.setdefault(manifest_path.parent, manifest_path.name)
        if found:
            candidates_by_language[language] = found

    roots = {}  # project_dir -> {language: runtime_str}
    for language, found in candidates_by_language.items():
        for project_dir in _keep_only_outermost(found.keys()):
            runtime_str = detect_runtime(project_dir, language)
            if runtime_str is None:
                runtime_str = f"{language} project (declared in {found[project_dir]}, no version specified)"
            roots.setdefault(project_dir, {})[language] = runtime_str

    def _sort_key(directory):
        rel = directory.relative_to(resolved).as_posix()
        return (len(directory.relative_to(resolved).parts), rel)

    results = []
    for directory in sorted(roots, key=_sort_key):
        rel = directory.relative_to(resolved).as_posix()
        results.append({"root": rel if rel != "." else ".", "languages": roots[directory]})

    if max_roots is not None and len(results) > max_roots:
        results = results[:max_roots]

    return results


def _detect_tool_versions(repo_path, tool_names):
    """Check an asdf/mise-style `.tool-versions` file for any of the
    given tool name aliases (e.g. {"java", "openjdk"}), used as a
    last-resort fallback by every detector below. A single
    `.tool-versions` file commonly declares several languages' runtime
    versions at once (one project-wide version-manager file rather
    than per-language manifests), so it's worth checking generically
    rather than duplicating this per language.
    """
    tv = _find_manifest(repo_path, ".tool-versions")
    text = _read(tv)
    if not text:
        return None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name, version = parts[0].lower(), parts[1]
        if name in tool_names:
            return f"{version} (declared in {_label(repo_path, tv)})"
    return None


def _detect_java(repo_path):
    pom = _find_manifest(repo_path, "pom.xml")
    text = _read(pom)
    if text:
        for pattern in (
            r"<maven\.compiler\.release>\s*([\w.\-]+)\s*</maven\.compiler\.release>",
            r"<maven\.compiler\.target>\s*([\w.\-]+)\s*</maven\.compiler\.target>",
            r"<maven\.compiler\.source>\s*([\w.\-]+)\s*</maven\.compiler\.source>",
            r"<java\.version>\s*([\w.\-]+)\s*</java\.version>",
        ):
            version = _search(pattern, text)
            if version:
                return f"Java {version} (declared in {_label(repo_path, pom)})"

    for gradle_name in ("build.gradle.kts", "build.gradle"):
        gradle = _find_manifest(repo_path, gradle_name)
        text = _read(gradle)
        if not text:
            continue
        version = (
            _search(r"languageVersion\.set\(JavaLanguageVersion\.of\((\d+)\)\)", text)
            or _search(r"sourceCompatibility\s*=\s*[\"']?(?:JavaVersion\.VERSION_)?([\w.]+)[\"']?", text)
        )
        if version:
            return f"Java {version.replace('_', '.')} (declared in {_label(repo_path, gradle)})"

    javaver_file = _find_manifest(repo_path, ".java-version")
    text = _read(javaver_file)
    if text and text.strip():
        return f"Java {text.strip().splitlines()[0]} (declared in {_label(repo_path, javaver_file)})"

    tv = _detect_tool_versions(repo_path, {"java", "openjdk", "temurin", "corretto", "zulu", "graalvm"})
    if tv:
        return f"Java {tv}"

    return None


def _detect_python(repo_path):
    pyproject = _find_manifest(repo_path, "pyproject.toml")
    version = _search(r'requires-python\s*=\s*["\']([^"\']+)["\']', _read(pyproject))
    if version:
        return f"Python {version} (declared in {_label(repo_path, pyproject)})"

    setup_cfg = _find_manifest(repo_path, "setup.cfg")
    version = _search(r"^python_requires\s*=\s*(.+)$", _read(setup_cfg), re.MULTILINE)
    if version:
        return f"Python {version.strip()} (declared in {_label(repo_path, setup_cfg)})"

    pyver_file = _find_manifest(repo_path, ".python-version")
    text = _read(pyver_file)
    if text and text.strip():
        return f"Python {text.strip().splitlines()[0]} (declared in {_label(repo_path, pyver_file)})"

    pipfile = _find_manifest(repo_path, "Pipfile")
    version = _search(r'python_version\s*=\s*["\']([^"\']+)["\']', _read(pipfile))
    if version:
        return f"Python {version} (declared in {_label(repo_path, pipfile)})"

    tv = _detect_tool_versions(repo_path, {"python", "python3", "cpython"})
    if tv:
        return f"Python {tv}"

    return None


def _detect_js_ts(repo_path):
    package_json = _find_manifest(repo_path, "package.json")
    version = _search(r'"engines"\s*:\s*\{[^}]*"node"\s*:\s*"([^"]+)"', _read(package_json))
    if version:
        return f"Node.js {version} (declared in {_label(repo_path, package_json)} engines)"

    nvmrc = _find_manifest(repo_path, ".nvmrc")
    text = _read(nvmrc)
    if text and text.strip():
        return f"Node.js {text.strip().splitlines()[0]} (declared in {_label(repo_path, nvmrc)})"

    node_ver_file = _find_manifest(repo_path, ".node-version")
    text = _read(node_ver_file)
    if text and text.strip():
        return f"Node.js {text.strip().splitlines()[0]} (declared in {_label(repo_path, node_ver_file)})"

    tv = _detect_tool_versions(repo_path, {"nodejs", "node"})
    if tv:
        return f"Node.js {tv}"

    return None


def _detect_go(repo_path):
    go_mod = _find_manifest(repo_path, "go.mod")
    version = _search(r"^go\s+([\d.]+)", _read(go_mod), re.MULTILINE)
    if version:
        return f"Go {version} (declared in {_label(repo_path, go_mod)})"

    go_work = _find_manifest(repo_path, "go.work")
    version = _search(r"^go\s+([\d.]+)", _read(go_work), re.MULTILINE)
    if version:
        return f"Go {version} (declared in {_label(repo_path, go_work)})"

    tv = _detect_tool_versions(repo_path, {"golang", "go"})
    if tv:
        return f"Go {tv}"

    return None


def _detect_ruby(repo_path):
    gemfile = _find_manifest(repo_path, "Gemfile")
    version = _search(r'ruby\s+["\']([\d.]+)["\']', _read(gemfile))
    if version:
        return f"Ruby {version} (declared in {_label(repo_path, gemfile)})"

    rbver_file = _find_manifest(repo_path, ".ruby-version")
    text = _read(rbver_file)
    if text and text.strip():
        return f"Ruby {text.strip().splitlines()[0]} (declared in {_label(repo_path, rbver_file)})"

    tv = _detect_tool_versions(repo_path, {"ruby"})
    if tv:
        return f"Ruby {tv}"

    return None


def _detect_rust(repo_path):
    cargo_toml = _find_manifest(repo_path, "Cargo.toml")
    version = _search(r'rust-version\s*=\s*["\']([^"\']+)["\']', _read(cargo_toml))
    if version:
        return f"Rust {version} (declared in {_label(repo_path, cargo_toml)})"

    toolchain = _find_manifest(repo_path, "rust-toolchain.toml") or _find_manifest(repo_path, "rust-toolchain")
    text = _read(toolchain)
    version = _search(r'channel\s*=\s*["\']([^"\']+)["\']', text) if text else None
    if not version and text and text.strip():
        version = text.strip()
    if version:
        return f"Rust {version} (declared in {_label(repo_path, toolchain)})"

    tv = _detect_tool_versions(repo_path, {"rust"})
    if tv:
        return f"Rust {tv}"

    return None


def _detect_kotlin(repo_path):
    # The most common real-world convention: a version catalog entry
    # or a bare property in gradle.properties, e.g. "kotlinVersion=2.0.0"
    # or "kotlin.version=2.0.0".
    gradle_props = _find_manifest(repo_path, "gradle.properties")
    text = _read(gradle_props)
    version = _search(r"^kotlin[Vv]ersion\s*=\s*(\S+)", text, re.MULTILINE) if text else None
    if not version and text:
        version = _search(r"^kotlin\.version\s*=\s*(\S+)", text, re.MULTILINE)
    if version:
        return f"Kotlin {version} (declared in {_label(repo_path, gradle_props)})"

    # The Kotlin Gradle plugin declaration itself, e.g.:
    #   kotlin("jvm") version "2.0.0"                (Kotlin DSL, build.gradle.kts)
    #   id "org.jetbrains.kotlin.jvm" version "2.0.0" (Groovy DSL, build.gradle)
    for gradle_name in ("build.gradle.kts", "build.gradle"):
        gradle_file = _find_manifest(repo_path, gradle_name)
        text = _read(gradle_file)
        if not text:
            continue
        version = (
            _search(r'kotlin\([^)]*\)\s*version\s*["\']([^"\']+)["\']', text)
            or _search(r'id\s*\(?\s*["\']org\.jetbrains\.kotlin[^"\']*["\']\s*\)?\s*version\s*["\']([^"\']+)["\']', text)
        )
        if version:
            return f"Kotlin {version} (declared in {_label(repo_path, gradle_file)})"

    tv = _detect_tool_versions(repo_path, {"kotlin"})
    if tv:
        return f"Kotlin {tv}"

    return None


def _detect_dotnet(repo_path):
    try:
        csproj_files = sorted(repo_path.glob("**/*.csproj"))
    except (OSError, ValueError):
        csproj_files = []
    csproj_files = [
        p for p in csproj_files
        if not any(part in _NOISE_DIRS for part in p.relative_to(repo_path).parts[:-1])
    ]
    csproj_files.sort(key=lambda p: len(p.relative_to(repo_path).parts))
    for csproj in csproj_files:
        version = _search(r"<TargetFramework>([^<]+)</TargetFramework>", _read(csproj))
        if version:
            return f".NET {version} (declared in {_label(repo_path, csproj)})"

    global_json = _find_manifest(repo_path, "global.json")
    version = _search(r'"version"\s*:\s*"([^"]+)"', _read(global_json))
    if version:
        return f".NET SDK {version} (declared in {_label(repo_path, global_json)})"

    tv = _detect_tool_versions(repo_path, {"dotnet-core", "dotnet"})
    if tv:
        return f".NET {tv}"

    return None


def _detect_c(repo_path):
    cmake = _find_manifest(repo_path, "CMakeLists.txt")
    text = _read(cmake)
    if text:
        version = _search(r"set\s*\(\s*CMAKE_C_STANDARD\s+(\d+)\s*\)", text, re.IGNORECASE)
        if version:
            return f"C{version} (declared in {_label(repo_path, cmake)})"
        version = _search(r"cmake_minimum_required\s*\(\s*VERSION\s+([\d.]+)", text, re.IGNORECASE)
        if version:
            return f"CMake >= {version} (declared in {_label(repo_path, cmake)})"
    return None


def _detect_cpp(repo_path):
    cmake = _find_manifest(repo_path, "CMakeLists.txt")
    text = _read(cmake)
    if text:
        version = _search(r"set\s*\(\s*CMAKE_CXX_STANDARD\s+(\d+)\s*\)", text, re.IGNORECASE)
        if version:
            return f"C++{version} (declared in {_label(repo_path, cmake)})"
        version = _search(r"cmake_minimum_required\s*\(\s*VERSION\s+([\d.]+)", text, re.IGNORECASE)
        if version:
            return f"CMake >= {version} (declared in {_label(repo_path, cmake)})"
    return None


def _detect_r(repo_path):
    # CRAN-style package manifest: Depends: R (>= 4.1.0), ...
    description = _find_manifest(repo_path, "DESCRIPTION")
    version = _search(r"Depends:.*?\bR\s*\(>=\s*([\d.]+)\)", _read(description), re.DOTALL)
    if version:
        return f"R >= {version} (declared in {_label(repo_path, description)})"

    # renv lockfile: {"R": {"Version": "4.2.1"}, ...}
    renv_lock = _find_manifest(repo_path, "renv.lock")
    version = _search(r'"R"\s*:\s*\{\s*"Version"\s*:\s*"([^"]+)"', _read(renv_lock))
    if version:
        return f"R {version} (declared in {_label(repo_path, renv_lock)})"

    return None


# language -> function(repo_path: Path) -> declared runtime string, or None.
_DETECTORS = {
    "Java": _detect_java,
    "Kotlin": _detect_kotlin,
    "Python": _detect_python,
    "JavaScript": _detect_js_ts,
    "TypeScript": _detect_js_ts,
    "Go": _detect_go,
    "Ruby": _detect_ruby,
    "Rust": _detect_rust,
    "C#": _detect_dotnet,
    "F#": _detect_dotnet,
    "C": _detect_c,
    "C++": _detect_cpp,
    "R": _detect_r,
}


def detect_runtime(repo_path, language):
    """Return a human-readable declared-runtime string for `language`
    (e.g. "Python >=3.8 (declared in pyproject.toml)"), sourced from
    `repo_path`'s own manifest files -- checked at the root first,
    then via a recursive fallback search if it's not there. Returns
    None if there's no meaningful runtime concept for this language
    (e.g. Markdown, JSON, TOML), or the project simply doesn't declare
    one. Results are cached per (repo_path, language) for this
    process's lifetime.
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


def detect_runtimes(repo_path, languages):
    """Return {language: runtime_string_or_None} for every language in
    the given iterable, all sourced from `repo_path`'s manifest files.
    """
    return {lang: detect_runtime(repo_path, lang) for lang in languages}
