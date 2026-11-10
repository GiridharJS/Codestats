import pytest

from src.runtime import detect_runtime, detect_runtimes


class TestDetectRuntimeJava:
    def test_reads_maven_compiler_release(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            "<project><properties>"
            "<maven.compiler.release>17</maven.compiler.release>"
            "</properties></project>"
        )
        result = detect_runtime(tmp_path, "Java")
        assert result == "Java 17 (declared in pom.xml)"

    def test_falls_back_to_compiler_source_when_no_release(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            "<project><properties>"
            "<maven.compiler.source>11</maven.compiler.source>"
            "</properties></project>"
        )
        result = detect_runtime(tmp_path, "Java")
        assert result == "Java 11 (declared in pom.xml)"

    def test_reads_gradle_source_compatibility_when_no_pom(self, tmp_path):
        (tmp_path / "build.gradle").write_text("sourceCompatibility = '21'\n")
        result = detect_runtime(tmp_path, "Java")
        assert result == "Java 21 (declared in build.gradle)"

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "Java") is None


class TestDetectRuntimePython:
    def test_reads_requires_python_from_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.9"\n')
        result = detect_runtime(tmp_path, "Python")
        assert result == "Python >=3.9 (declared in pyproject.toml)"

    def test_falls_back_to_setup_cfg(self, tmp_path):
        (tmp_path / "setup.cfg").write_text("[options]\npython_requires = >=3.8\n")
        result = detect_runtime(tmp_path, "Python")
        assert result == "Python >=3.8 (declared in setup.cfg)"

    def test_falls_back_to_python_version_file(self, tmp_path):
        (tmp_path / ".python-version").write_text("3.12.1\n")
        result = detect_runtime(tmp_path, "Python")
        assert result == "Python 3.12.1 (declared in .python-version)"

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "Python") is None


class TestDetectRuntimeJsTs:
    def test_reads_node_engine_from_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"name": "app", "engines": {"node": ">=18"}}'
        )
        assert detect_runtime(tmp_path, "JavaScript") == "Node.js >=18 (declared in package.json engines)"
        assert detect_runtime(tmp_path, "TypeScript") == "Node.js >=18 (declared in package.json engines)"

    def test_falls_back_to_nvmrc(self, tmp_path):
        (tmp_path / ".nvmrc").write_text("18.16.0\n")
        result = detect_runtime(tmp_path, "JavaScript")
        assert result == "Node.js 18.16.0 (declared in .nvmrc)"

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "JavaScript") is None


class TestDetectRuntimeGo:
    def test_reads_go_directive(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/app\n\ngo 1.21\n")
        result = detect_runtime(tmp_path, "Go")
        assert result == "Go 1.21 (declared in go.mod)"

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "Go") is None


class TestDetectRuntimeRuby:
    def test_reads_ruby_version_from_gemfile(self, tmp_path):
        (tmp_path / "Gemfile").write_text('source "https://rubygems.org"\nruby "3.2.0"\n')
        result = detect_runtime(tmp_path, "Ruby")
        assert result == "Ruby 3.2.0 (declared in Gemfile)"

    def test_falls_back_to_ruby_version_file(self, tmp_path):
        (tmp_path / ".ruby-version").write_text("3.1.2\n")
        result = detect_runtime(tmp_path, "Ruby")
        assert result == "Ruby 3.1.2 (declared in .ruby-version)"

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "Ruby") is None


class TestDetectRuntimeRust:
    def test_reads_rust_version_from_cargo_toml(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "app"\nrust-version = "1.70"\n'
        )
        result = detect_runtime(tmp_path, "Rust")
        assert result == "Rust 1.70 (declared in Cargo.toml)"

    def test_falls_back_to_rust_toolchain_file(self, tmp_path):
        (tmp_path / "rust-toolchain").write_text("1.65.0\n")
        result = detect_runtime(tmp_path, "Rust")
        assert result == "Rust 1.65.0 (declared in rust-toolchain)"

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "Rust") is None


class TestDetectRuntimeDotnet:
    def test_reads_target_framework_from_csproj(self, tmp_path):
        (tmp_path / "app.csproj").write_text(
            "<Project><PropertyGroup><TargetFramework>net8.0</TargetFramework>"
            "</PropertyGroup></Project>"
        )
        result = detect_runtime(tmp_path, "C#")
        assert result == ".NET net8.0 (declared in app.csproj)"

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "C#") is None


class TestDetectRuntimeKotlin:
    def test_reads_kotlin_version_from_gradle_properties(self, tmp_path):
        (tmp_path / "gradle.properties").write_text(
            "version=7.1.0-SNAPSHOT\n\n"
            "org.gradle.caching=true\n"
            "org.gradle.jvmargs=-Xmx2048m\n\n"
            "kotlinVersion=2.4.10\n"
            "byteBuddyVersion=1.17.6\n"
        )
        result = detect_runtime(tmp_path, "Kotlin")
        assert result == "Kotlin 2.4.10 (declared in gradle.properties)"

    def test_reads_dotted_kotlin_version_property(self, tmp_path):
        (tmp_path / "gradle.properties").write_text("kotlin.version=1.9.24\n")
        result = detect_runtime(tmp_path, "Kotlin")
        assert result == "Kotlin 1.9.24 (declared in gradle.properties)"

    def test_reads_kotlin_dsl_plugin_declaration(self, tmp_path):
        (tmp_path / "build.gradle.kts").write_text(
            'plugins {\n    kotlin("jvm") version "2.0.0"\n}\n'
        )
        result = detect_runtime(tmp_path, "Kotlin")
        assert result == "Kotlin 2.0.0 (declared in build.gradle.kts)"

    def test_reads_groovy_dsl_plugin_declaration(self, tmp_path):
        (tmp_path / "build.gradle").write_text(
            'plugins {\n    id "org.jetbrains.kotlin.jvm" version "1.9.22"\n}\n'
        )
        result = detect_runtime(tmp_path, "Kotlin")
        assert result == "Kotlin 1.9.22 (declared in build.gradle)"

    def test_gradle_properties_takes_priority_over_plugin_declaration(self, tmp_path):
        (tmp_path / "gradle.properties").write_text("kotlinVersion=2.4.10\n")
        (tmp_path / "build.gradle").write_text(
            'plugins {\n    id "org.jetbrains.kotlin.jvm" version "1.9.22"\n}\n'
        )
        result = detect_runtime(tmp_path, "Kotlin")
        assert result == "Kotlin 2.4.10 (declared in gradle.properties)"

    def test_falls_back_to_tool_versions(self, tmp_path):
        (tmp_path / ".tool-versions").write_text("kotlin 1.9.0\n")
        result = detect_runtime(tmp_path, "Kotlin")
        assert result == "Kotlin 1.9.0 (declared in .tool-versions)"

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "Kotlin") is None

    def test_java_only_gradle_file_does_not_yield_kotlin_version(self, tmp_path):
        # A plain Java project's build.gradle has no Kotlin plugin
        # declaration at all -- must not false-positive.
        (tmp_path / "build.gradle").write_text(
            "plugins {\n    id 'java'\n}\n\n"
            "java {\n    sourceCompatibility = JavaVersion.VERSION_17\n}\n"
        )
        assert detect_runtime(tmp_path, "Kotlin") is None
        assert detect_runtime(tmp_path, "Java") == "Java 17 (declared in build.gradle)"


class TestDetectRuntimeC:
    def test_reads_cmake_c_standard(self, tmp_path):
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.16)\nset(CMAKE_C_STANDARD 11)\n"
        )
        result = detect_runtime(tmp_path, "C")
        assert result == "C11 (declared in CMakeLists.txt)"

    def test_falls_back_to_cmake_minimum_version(self, tmp_path):
        (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n")
        result = detect_runtime(tmp_path, "C")
        assert result == "CMake >= 3.20 (declared in CMakeLists.txt)"

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "C") is None


class TestDetectRuntimeCpp:
    def test_reads_cmake_cxx_standard(self, tmp_path):
        (tmp_path / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.16)\nset(CMAKE_CXX_STANDARD 17)\n"
        )
        result = detect_runtime(tmp_path, "C++")
        assert result == "C++17 (declared in CMakeLists.txt)"

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "C++") is None


class TestDetectRuntimeR:
    def test_reads_r_version_from_description(self, tmp_path):
        (tmp_path / "DESCRIPTION").write_text(
            "Package: mypkg\nDepends: R (>= 4.1.0), methods\n"
        )
        result = detect_runtime(tmp_path, "R")
        assert result == "R >= 4.1.0 (declared in DESCRIPTION)"

    def test_falls_back_to_renv_lock(self, tmp_path):
        (tmp_path / "renv.lock").write_text('{"R": {"Version": "4.2.1"}, "Packages": {}}')
        result = detect_runtime(tmp_path, "R")
        assert result == "R 4.2.1 (declared in renv.lock)"

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "R") is None


class TestManifestFallbackSearch:
    def test_go_mod_found_when_nested_in_subdirectory(self, tmp_path):
        # codestats was pointed at a parent folder that isn't the
        # module root itself -- go.mod lives one level down.
        sub = tmp_path / "cmd" / "api"
        sub.mkdir(parents=True)
        (sub / "go.mod").write_text("module example.com/api\n\ngo 1.20\n")
        result = detect_runtime(tmp_path, "Go")
        assert result == "Go 1.20 (declared in cmd/api/go.mod)"

    def test_prefers_root_manifest_over_nested_one(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/root\n\ngo 1.22\n")
        sub = tmp_path / "vendor" / "dep"
        sub.mkdir(parents=True)
        (sub / "go.mod").write_text("module example.com/dep\n\ngo 1.18\n")
        result = detect_runtime(tmp_path, "Go")
        assert result == "Go 1.22 (declared in go.mod)"

    def test_shallowest_nested_match_wins_when_no_root_manifest(self, tmp_path):
        shallow = tmp_path / "service-a"
        shallow.mkdir()
        (shallow / "go.mod").write_text("module a\n\ngo 1.19\n")
        deep = tmp_path / "service-b" / "internal" / "pkg"
        deep.mkdir(parents=True)
        (deep / "go.mod").write_text("module b\n\ngo 1.21\n")
        result = detect_runtime(tmp_path, "Go")
        assert result == "Go 1.19 (declared in service-a/go.mod)"

    def test_noise_directories_are_skipped(self, tmp_path):
        # A go.mod that only exists inside node_modules/vendor/etc.
        # belongs to a dependency, not the scanned project -- it
        # should never be picked up even as a fallback.
        noisy = tmp_path / "node_modules" / "some-dep"
        noisy.mkdir(parents=True)
        (noisy / "go.mod").write_text("module some-dep\n\ngo 1.15\n")
        assert detect_runtime(tmp_path, "Go") is None

    def test_dotnet_csproj_search_also_skips_noise_dirs(self, tmp_path):
        noisy = tmp_path / "bin" / "Debug"
        noisy.mkdir(parents=True)
        (noisy / "vendored.csproj").write_text(
            "<Project><PropertyGroup><TargetFramework>net6.0</TargetFramework>"
            "</PropertyGroup></Project>"
        )
        assert detect_runtime(tmp_path, "C#") is None


class TestDetectRuntimeGeneral:
    def test_unknown_language_returns_none(self, tmp_path):
        assert detect_runtime(tmp_path, "SomeMadeUpLanguage") is None

    def test_language_with_no_runtime_concept_returns_none(self, tmp_path):
        # Markdown, TOML, JSON, YAML etc. have no meaningful runtime
        # version and are deliberately absent from the detector table.
        assert detect_runtime(tmp_path, "Markdown") is None
        assert detect_runtime(tmp_path, "TOML") is None
        assert detect_runtime(tmp_path, "JSON") is None

    def test_results_are_cached_per_repo_and_language(self, tmp_path):
        from src import runtime as runtime_module
        runtime_module._cache.clear()
        (tmp_path / "go.mod").write_text("module app\n\ngo 1.20\n")
        first = detect_runtime(tmp_path, "Go")
        key = (str(tmp_path.resolve()), "Go")
        assert key in runtime_module._cache
        second = detect_runtime(tmp_path, "Go")
        assert first == second == "Go 1.20 (declared in go.mod)"

    def test_missing_manifest_file_does_not_raise(self, tmp_path):
        assert detect_runtime(tmp_path / "does" / "not" / "exist", "Python") is None


class TestToolVersionsFallback:
    def test_single_file_covers_multiple_languages(self, tmp_path):
        (tmp_path / ".tool-versions").write_text(
            "nodejs 20.5.0\npython 3.11.4\njava openjdk-17.0.2\nruby 3.2.0\ngolang 1.21.0\nrust 1.70.0\n"
        )
        assert detect_runtime(tmp_path, "JavaScript") == "Node.js 20.5.0 (declared in .tool-versions)"
        assert detect_runtime(tmp_path, "Python") == "Python 3.11.4 (declared in .tool-versions)"
        assert detect_runtime(tmp_path, "Java") == "Java openjdk-17.0.2 (declared in .tool-versions)"
        assert detect_runtime(tmp_path, "Ruby") == "Ruby 3.2.0 (declared in .tool-versions)"
        assert detect_runtime(tmp_path, "Go") == "Go 1.21.0 (declared in .tool-versions)"
        assert detect_runtime(tmp_path, "Rust") == "Rust 1.70.0 (declared in .tool-versions)"

    def test_dedicated_manifest_takes_priority_over_tool_versions(self, tmp_path):
        (tmp_path / "go.mod").write_text("module app\n\ngo 1.22\n")
        (tmp_path / ".tool-versions").write_text("golang 1.18.0\n")
        assert detect_runtime(tmp_path, "Go") == "Go 1.22 (declared in go.mod)"

    def test_comments_and_blank_lines_ignored(self, tmp_path):
        (tmp_path / ".tool-versions").write_text("# a comment\n\nruby 3.2.0  # inline note\n")
        assert detect_runtime(tmp_path, "Ruby") == "Ruby 3.2.0 (declared in .tool-versions)"


class TestFindProjectRoots:
    def test_finds_distinct_roots_per_language(self, tmp_path):
        from src.runtime import find_project_roots

        (tmp_path / "api").mkdir()
        (tmp_path / "api" / "go.mod").write_text("module api\n\ngo 1.20\n")
        (tmp_path / "web").mkdir()
        (tmp_path / "web" / "package.json").write_text('{"engines": {"node": ">=18"}}')

        roots = find_project_roots(tmp_path)
        by_root = {r["root"]: r["languages"] for r in roots}

        assert by_root["api"]["Go"] == "Go 1.20 (declared in go.mod)"
        assert "Node.js >=18" in by_root["web"]["JavaScript"]

    def test_filters_by_detected_languages(self, tmp_path):
        from src.runtime import find_project_roots

        (tmp_path / "build.gradle").write_text("sourceCompatibility = '17'\n")

        # Without a language filter, both Java and Kotlin match the
        # same manifest (they share Gradle/Maven filenames).
        unfiltered = find_project_roots(tmp_path)
        assert set(unfiltered[0]["languages"].keys()) == {"Java", "Kotlin"}

        # Filtered to only languages actually found in the scan,
        # Kotlin (no .kt files present) must not appear.
        filtered = find_project_roots(tmp_path, detected_languages={"Java"})
        assert set(filtered[0]["languages"].keys()) == {"Java"}

    def test_no_manifests_returns_empty_list(self, tmp_path):
        from src.runtime import find_project_roots
        assert find_project_roots(tmp_path) == []

    def test_ignores_manifests_in_noise_directories(self, tmp_path):
        from src.runtime import find_project_roots

        vendored = tmp_path / "node_modules" / "some-dep"
        vendored.mkdir(parents=True)
        (vendored / "go.mod").write_text("module dep\n\ngo 1.18\n")

        assert find_project_roots(tmp_path) == []

    def test_root_level_manifest_reports_dot_as_root(self, tmp_path):
        from src.runtime import find_project_roots

        (tmp_path / "go.mod").write_text("module app\n\ngo 1.21\n")
        roots = find_project_roots(tmp_path)
        assert roots[0]["root"] == "."

    def test_nested_manifest_of_same_language_is_collapsed_into_outer_root(self, tmp_path):
        # Regression test: a large codebase with a top-level go.mod
        # commonly has MANY deeper, unrelated go.mod files scattered
        # through its own test fixtures / internal tooling (verified
        # against a real clone of golang/go: 20+ of them). Those must
        # be treated as part of the outer project, not reported as
        # separate top-level roots -- otherwise --projects becomes
        # noise instead of a useful overview.
        from src.runtime import find_project_roots

        (tmp_path / "go.mod").write_text("module app\n\ngo 1.21\n")
        nested = tmp_path / "internal" / "testdata" / "fixture"
        nested.mkdir(parents=True)
        (nested / "go.mod").write_text("module fixture\n\ngo 1.16\n")

        roots = find_project_roots(tmp_path)
        assert [r["root"] for r in roots] == ["."]

    def test_sibling_projects_of_same_language_are_not_collapsed(self, tmp_path):
        # Two independent (non-nested) directories with the same
        # language's manifest must both still show up.
        from src.runtime import find_project_roots

        a = tmp_path / "service-a"
        a.mkdir()
        (a / "go.mod").write_text("module a\n\ngo 1.20\n")
        b = tmp_path / "service-b"
        b.mkdir()
        (b / "go.mod").write_text("module b\n\ngo 1.21\n")

        roots = find_project_roots(tmp_path)
        assert sorted(r["root"] for r in roots) == ["service-a", "service-b"]

    def test_different_language_nested_inside_a_root_still_reported(self, tmp_path):
        # A DIFFERENT language nested inside another language's root
        # is a genuinely separate thing (e.g. a Node tooling subfolder
        # inside a Python service) and must not be collapsed away.
        from src.runtime import find_project_roots

        (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.11"\n')
        tooling = tmp_path / "tools" / "web"
        tooling.mkdir(parents=True)
        (tooling / "package.json").write_text('{"engines": {"node": ">=18"}}')

        roots = find_project_roots(tmp_path)
        by_root = {r["root"]: r["languages"] for r in roots}
        assert "Python" in by_root["."]
        assert "JavaScript" in by_root["tools/web"]

    def test_max_roots_caps_and_keeps_shallowest_first(self, tmp_path):
        from src.runtime import find_project_roots

        for i in range(5):
            d = tmp_path / f"service-{i}"
            d.mkdir()
            (d / "go.mod").write_text(f"module service{i}\n\ngo 1.2{i}\n")

        capped = find_project_roots(tmp_path, max_roots=2)
        assert len(capped) == 2
        uncapped = find_project_roots(tmp_path)
        assert len(uncapped) == 5
        assert capped == uncapped[:2]


class TestDetectRuntimes:
    def test_returns_dict_for_all_given_languages(self, tmp_path):
        (tmp_path / "go.mod").write_text("module app\n\ngo 1.22\n")
        result = detect_runtimes(tmp_path, ["Go", "Markdown", "SomeMadeUpLanguage"])
        assert set(result.keys()) == {"Go", "Markdown", "SomeMadeUpLanguage"}
        assert result["Go"] == "Go 1.22 (declared in go.mod)"
        assert result["Markdown"] is None
        assert result["SomeMadeUpLanguage"] is None

    def test_empty_input_returns_empty_dict(self, tmp_path):
        assert detect_runtimes(tmp_path, []) == {}
