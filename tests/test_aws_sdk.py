import pytest

from src.aws_sdk import AwsSdkInfo, detect_aws_sdk, detect_aws_sdks


class TestDetectAwsSdkPython:
    def test_reads_boto3_pinned_version_from_requirements_txt(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("boto3==1.34.100\nrequests==2.31.0\n")
        result = detect_aws_sdk(tmp_path, "Python")
        assert result == AwsSdkInfo(sdk="boto3 1.34.100", manifest="requirements.txt")

    def test_reads_botocore_when_boto3_absent(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("botocore>=1.34.0\n")
        result = detect_aws_sdk(tmp_path, "Python")
        assert result == AwsSdkInfo(sdk="botocore 1.34.0", manifest="requirements.txt")

    def test_reads_poetry_style_pyproject_entry(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.poetry.dependencies]\nboto3 = "^1.34"\n')
        result = detect_aws_sdk(tmp_path, "Python")
        assert result == AwsSdkInfo(sdk="boto3 ^1.34", manifest="pyproject.toml")

    def test_reads_pipfile_entry(self, tmp_path):
        (tmp_path / "Pipfile").write_text('[packages]\nboto3 = "*"\n')
        result = detect_aws_sdk(tmp_path, "Python")
        assert result == AwsSdkInfo(sdk="boto3 *", manifest="Pipfile")

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_aws_sdk(tmp_path, "Python") is None

    def test_unrelated_dependency_returns_none(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==3.0.0\nrequests==2.31.0\n")
        assert detect_aws_sdk(tmp_path, "Python") is None


class TestDetectAwsSdkJsTs:
    def test_reads_v3_client_package(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"dependencies": {"@aws-sdk/client-s3": "^3.600.0"}}'
        )
        result = detect_aws_sdk(tmp_path, "JavaScript")
        assert result == AwsSdkInfo(sdk="@aws-sdk/client-s3 ^3.600.0", manifest="package.json")

    def test_reports_count_of_additional_v3_packages(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"dependencies": {'
            '"@aws-sdk/client-s3": "^3.600.0",'
            '"@aws-sdk/client-dynamodb": "^3.600.0",'
            '"@aws-sdk/client-sqs": "^3.600.0"'
            '}}'
        )
        result = detect_aws_sdk(tmp_path, "JavaScript")
        assert "+2 more @aws-sdk/* packages" in result.sdk
        assert result.manifest == "package.json"

    def test_reads_v2_monolithic_package(self, tmp_path):
        (tmp_path / "package.json").write_text('{"dependencies": {"aws-sdk": "^2.1600.0"}}')
        result = detect_aws_sdk(tmp_path, "JavaScript")
        assert result == AwsSdkInfo(sdk="aws-sdk ^2.1600.0", manifest="package.json")

    def test_typescript_uses_same_detector_as_javascript(self, tmp_path):
        (tmp_path / "package.json").write_text('{"dependencies": {"aws-sdk": "^2.1600.0"}}')
        assert detect_aws_sdk(tmp_path, "TypeScript") == detect_aws_sdk(tmp_path, "JavaScript")

    def test_no_aws_dependency_returns_none(self, tmp_path):
        (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}')
        assert detect_aws_sdk(tmp_path, "JavaScript") is None


class TestDetectAwsSdkGo:
    def test_reads_v2_single_line_require(self, tmp_path):
        (tmp_path / "go.mod").write_text(
            "module example.com/foo\n\ngo 1.22\n\nrequire github.com/aws/aws-sdk-go-v2 v1.30.0\n"
        )
        result = detect_aws_sdk(tmp_path, "Go")
        assert result == AwsSdkInfo(sdk="aws-sdk-go-v2 v1.30.0", manifest="go.mod")

    def test_reads_v2_from_require_block(self, tmp_path):
        (tmp_path / "go.mod").write_text(
            "module example.com/foo\n\ngo 1.22\n\n"
            "require (\n\tgithub.com/aws/aws-sdk-go-v2 v1.30.0\n\tgithub.com/pkg/errors v0.9.1\n)\n"
        )
        result = detect_aws_sdk(tmp_path, "Go")
        assert result == AwsSdkInfo(sdk="aws-sdk-go-v2 v1.30.0", manifest="go.mod")

    def test_reads_v1_when_v2_absent(self, tmp_path):
        (tmp_path / "go.mod").write_text(
            "module example.com/foo\n\ngo 1.22\n\nrequire github.com/aws/aws-sdk-go v1.51.0\n"
        )
        result = detect_aws_sdk(tmp_path, "Go")
        assert result == AwsSdkInfo(sdk="aws-sdk-go v1.51.0", manifest="go.mod")

    def test_v1_regex_does_not_false_match_v2_module_path(self, tmp_path):
        # github.com/aws/aws-sdk-go is a PREFIX of .../aws-sdk-go-v2 --
        # the v1 pattern must not accidentally match the v2 module.
        (tmp_path / "go.mod").write_text(
            "module example.com/foo\n\ngo 1.22\n\nrequire github.com/aws/aws-sdk-go-v2 v1.30.0\n"
        )
        result = detect_aws_sdk(tmp_path, "Go")
        assert result.sdk.startswith("aws-sdk-go-v2")

    def test_reads_from_nested_go_mod(self, tmp_path):
        sub = tmp_path / "misc"
        sub.mkdir()
        (sub / "go.mod").write_text(
            "module example.com/misc\n\ngo 1.22\n\nrequire github.com/aws/aws-sdk-go-v2 v1.30.0\n"
        )
        result = detect_aws_sdk(tmp_path, "Go")
        assert result == AwsSdkInfo(sdk="aws-sdk-go-v2 v1.30.0", manifest="misc/go.mod")

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_aws_sdk(tmp_path, "Go") is None


class TestDetectAwsSdkJava:
    def test_reads_v2_from_pom_xml(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            "<project><dependencies><dependency>"
            "<groupId>software.amazon.awssdk</groupId>"
            "<artifactId>s3</artifactId>"
            "<version>2.25.40</version>"
            "</dependency></dependencies></project>"
        )
        result = detect_aws_sdk(tmp_path, "Java")
        assert result == AwsSdkInfo(sdk="AWS SDK for Java v2 (s3) 2.25.40", manifest="pom.xml")

    def test_reads_v1_from_pom_xml(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            "<project><dependencies><dependency>"
            "<groupId>com.amazonaws</groupId>"
            "<artifactId>aws-java-sdk-s3</artifactId>"
            "<version>1.12.700</version>"
            "</dependency></dependencies></project>"
        )
        result = detect_aws_sdk(tmp_path, "Java")
        assert result == AwsSdkInfo(sdk="AWS SDK for Java v1 (aws-java-sdk-s3) 1.12.700", manifest="pom.xml")

    def test_reads_from_build_gradle(self, tmp_path):
        (tmp_path / "build.gradle").write_text(
            "implementation 'software.amazon.awssdk:s3:2.25.40'\n"
        )
        result = detect_aws_sdk(tmp_path, "Java")
        assert result == AwsSdkInfo(sdk="AWS SDK for Java v2 2.25.40", manifest="build.gradle")

    def test_kotlin_uses_same_detector_as_java(self, tmp_path):
        (tmp_path / "build.gradle").write_text(
            "implementation 'software.amazon.awssdk:s3:2.25.40'\n"
        )
        assert detect_aws_sdk(tmp_path, "Kotlin") == detect_aws_sdk(tmp_path, "Java")

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_aws_sdk(tmp_path, "Java") is None


class TestDetectAwsSdkRuby:
    def test_reads_versioned_gem(self, tmp_path):
        (tmp_path / "Gemfile").write_text('gem "aws-sdk-s3", "~> 1.130"\n')
        result = detect_aws_sdk(tmp_path, "Ruby")
        assert result == AwsSdkInfo(sdk="aws-sdk-s3 ~> 1.130", manifest="Gemfile")

    def test_reads_unversioned_gem(self, tmp_path):
        (tmp_path / "Gemfile").write_text('gem "aws-sdk"\n')
        result = detect_aws_sdk(tmp_path, "Ruby")
        assert result == AwsSdkInfo(sdk="aws-sdk (unpinned)", manifest="Gemfile")

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_aws_sdk(tmp_path, "Ruby") is None


class TestDetectAwsSdkDotnet:
    def test_reads_from_csproj(self, tmp_path):
        (tmp_path / "app.csproj").write_text(
            '<Project><ItemGroup>'
            '<PackageReference Include="AWSSDK.S3" Version="3.7.300.0" />'
            '</ItemGroup></Project>'
        )
        result = detect_aws_sdk(tmp_path, "C#")
        assert result == AwsSdkInfo(sdk="AWSSDK.S3 3.7.300.0", manifest="app.csproj")

    def test_finds_csproj_in_subdirectory(self, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "app.csproj").write_text(
            '<Project><ItemGroup>'
            '<PackageReference Include="AWSSDK.DynamoDBv2" Version="3.7.100.0" />'
            '</ItemGroup></Project>'
        )
        result = detect_aws_sdk(tmp_path, "C#")
        assert result == AwsSdkInfo(sdk="AWSSDK.DynamoDBv2 3.7.100.0", manifest="src/app.csproj")

    def test_f_sharp_uses_same_detector_as_csharp(self, tmp_path):
        (tmp_path / "app.csproj").write_text(
            '<Project><ItemGroup>'
            '<PackageReference Include="AWSSDK.S3" Version="3.7.300.0" />'
            '</ItemGroup></Project>'
        )
        assert detect_aws_sdk(tmp_path, "F#") == detect_aws_sdk(tmp_path, "C#")

    def test_no_csproj_returns_none(self, tmp_path):
        assert detect_aws_sdk(tmp_path, "C#") is None


class TestDetectAwsSdkRust:
    def test_reads_simple_string_version(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[dependencies]\naws-config = "1.5"\n')
        result = detect_aws_sdk(tmp_path, "Rust")
        assert result == AwsSdkInfo(sdk="aws-config 1.5", manifest="Cargo.toml")

    def test_reads_table_style_version(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text(
            '[dependencies]\naws-sdk-s3 = { version = "1.40", features = ["rustls"] }\n'
        )
        result = detect_aws_sdk(tmp_path, "Rust")
        assert result == AwsSdkInfo(sdk="aws-sdk-s3 1.40", manifest="Cargo.toml")

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_aws_sdk(tmp_path, "Rust") is None


class TestDetectAwsSdkCpp:
    def test_reads_aws_sdk_cpp_reference(self, tmp_path):
        (tmp_path / "CMakeLists.txt").write_text(
            "find_package(AWSSDK REQUIRED COMPONENTS s3)\n"
            "target_link_libraries(myapp AWSSDK::s3)\n"
        )
        result = detect_aws_sdk(tmp_path, "C++")
        assert result == AwsSdkInfo(sdk="aws-sdk-cpp", manifest="CMakeLists.txt")

    def test_no_manifest_returns_none(self, tmp_path):
        assert detect_aws_sdk(tmp_path, "C++") is None


class TestDetectAwsSdkGeneral:
    def test_unsupported_language_returns_none(self, tmp_path):
        assert detect_aws_sdk(tmp_path, "Markdown") is None
        assert detect_aws_sdk(tmp_path, "JSON") is None

    def test_detect_aws_sdks_returns_dict_for_every_language(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("boto3==1.34.100\n")
        result = detect_aws_sdks(tmp_path, ["Python", "Go", "Markdown"])
        assert result == {
            "Python": AwsSdkInfo(sdk="boto3 1.34.100", manifest="requirements.txt"),
            "Go": None,
            "Markdown": None,
        }

    def test_result_is_a_namedtuple_with_sdk_and_manifest_fields(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("boto3==1.34.100\n")
        result = detect_aws_sdk(tmp_path, "Python")
        assert result.sdk == "boto3 1.34.100"
        assert result.manifest == "requirements.txt"

    def test_results_are_cached_per_repo_and_language(self, tmp_path, monkeypatch):
        (tmp_path / "requirements.txt").write_text("boto3==1.34.100\n")
        first = detect_aws_sdk(tmp_path, "Python")

        # Even if the manifest changes afterward, the cached answer
        # for this (repo, language) pair should still be returned --
        # same caching contract as runtime.detect_runtime.
        (tmp_path / "requirements.txt").write_text("boto3==2.0.0\n")
        second = detect_aws_sdk(tmp_path, "Python")
        assert first == second

    def test_a_broken_detector_never_raises_out_of_detect_aws_sdk(self, tmp_path, monkeypatch):
        from src import aws_sdk as aws_sdk_module

        def broken_detector(repo_path):
            raise ValueError("simulated failure")

        monkeypatch.setitem(aws_sdk_module._DETECTORS, "Python", broken_detector)
        assert detect_aws_sdk(tmp_path, "Python") is None
