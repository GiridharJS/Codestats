import pytest

from src.counter import FileStats
from src.report import (
    aggregate, compute_percentages, format_bar, format_table,
    generate_pdf, sorted_languages, totals,
)


@pytest.fixture
def sample_file_stats():
    return [
        FileStats(path="a.py", language="Python", lines=100, blank=10, comment=20, code=70),
        FileStats(path="b.py", language="Python", lines=50, blank=5, comment=5, code=40),
        FileStats(path="c.go", language="Go", lines=60, blank=10, comment=10, code=40),
    ]


class TestAggregate:
    def test_groups_by_language(self, sample_file_stats):
        summary = aggregate(sample_file_stats)
        assert set(summary.keys()) == {"Python", "Go"}
        assert summary["Python"]["files"] == 2
        assert summary["Python"]["code"] == 110
        assert summary["Go"]["files"] == 1
        assert summary["Go"]["code"] == 40

    def test_skips_none_entries(self, sample_file_stats):
        stats_with_none = sample_file_stats + [None]
        summary = aggregate(stats_with_none)
        assert totals(summary)["files"] == 3

    def test_empty_input_returns_empty_summary(self):
        assert aggregate([]) == {}


class TestComputePercentages:
    def test_percentages_sum_to_100(self, sample_file_stats):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary, key="code")
        assert round(sum(percentages.values()), 5) == 100.0

    def test_correct_ratio(self, sample_file_stats):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary, key="code")
        # Python: 110 code lines, JS: 40 code lines, total 150
        assert round(percentages["Python"], 2) == round(110 / 150 * 100, 2)
        assert round(percentages["Go"], 2) == round(40 / 150 * 100, 2)

    def test_empty_summary_returns_empty_dict(self):
        assert compute_percentages({}) == {}

    def test_zero_total_returns_zero_percentages(self):
        summary = {"Python": {"files": 1, "lines": 0, "blank": 0, "comment": 0, "code": 0}}
        percentages = compute_percentages(summary, key="code")
        assert percentages == {"Python": 0.0}


class TestTotals:
    def test_sums_across_languages(self, sample_file_stats):
        summary = aggregate(sample_file_stats)
        t = totals(summary)
        assert t["files"] == 3
        assert t["lines"] == 210
        assert t["code"] == 150
        assert t["blank"] == 25
        assert t["comment"] == 35


class TestSortedLanguages:
    def test_sorts_descending_by_metric(self, sample_file_stats):
        summary = aggregate(sample_file_stats)
        assert sorted_languages(summary, sort_by="code") == ["Python", "Go"]
        assert sorted_languages(summary, sort_by="files") == ["Python", "Go"]


class TestFormatTable:
    def test_contains_all_languages_and_total_row(self, sample_file_stats):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        table = format_table(summary, percentages)
        assert "Python" in table
        assert "Go" in table
        assert "Total" in table

    def test_empty_summary_message(self):
        assert format_table({}, {}) == "No recognised source files found."


class TestFormatBar:
    def test_bar_contains_language_names(self, sample_file_stats):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        bar = format_bar(percentages, use_color=False)
        assert "Python" in bar
        assert "Go" in bar

    def test_empty_percentages_returns_empty_string(self):
        assert format_bar({}) == ""

    def test_no_color_strips_ansi_codes(self, sample_file_stats):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        bar = format_bar(percentages, use_color=False)
        assert "\033[" not in bar


class TestGeneratePdf:
    def test_creates_a_pdf_file(self, sample_file_stats, tmp_path):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        output = tmp_path / "report.pdf"

        result_path = generate_pdf(summary, percentages, output, repo_label="my-repo")

        assert result_path == output
        assert output.exists()
        assert output.stat().st_size > 0
        with open(output, "rb") as f:
            assert f.read(5) == b"%PDF-"  # valid PDF file signature

    def test_empty_summary_still_produces_valid_pdf(self, tmp_path):
        output = tmp_path / "empty.pdf"
        generate_pdf({}, {}, output)
        assert output.exists()
        with open(output, "rb") as f:
            assert f.read(5) == b"%PDF-"

    def test_pdf_contains_expected_text(self, sample_file_stats, tmp_path):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        output = tmp_path / "report.pdf"
        generate_pdf(summary, percentages, output, repo_label="my-repo")

        from pypdf import PdfReader
        text = PdfReader(str(output)).pages[0].extract_text()
        assert "Python" in text
        assert "Go" in text
        assert "my-repo" in text
        assert "TOTAL" in text

    def test_accepts_string_path_as_well_as_path_object(self, sample_file_stats, tmp_path):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        output = str(tmp_path / "report.pdf")
        result_path = generate_pdf(summary, percentages, output)
        assert result_path.exists()


class TestFormatSkippedTable:
    def test_empty_list_message(self):
        from src.report import format_skipped_table
        assert format_skipped_table([]) == "Skipped files: 0"

    def test_lists_each_skipped_file_and_reason(self):
        from src.report import format_skipped_table
        skipped = [
            ("main.exe", None, "unsupported file type"),
            ("data.py", "Python", "binary or unreadable file"),
        ]
        table = format_skipped_table(skipped)
        assert "main.exe" in table
        assert "data.py" in table
        assert "Python" in table
        assert "unsupported file type" in table
        assert "Total skipped: 2" in table


class TestGeneratePdfSkipped:
    def test_pdf_includes_skipped_section_when_filewise(self, sample_file_stats, tmp_path):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        output = tmp_path / "report.pdf"
        skipped = [("weird.exe", None, "unsupported file type")]

        generate_pdf(summary, percentages, output, repo_label="repo", skipped=skipped, filewise=True)

        from pypdf import PdfReader
        text = PdfReader(str(output)).pages[0].extract_text()
        assert "Skipped Files" in text
        assert "weird.exe" in text
        assert "Total skipped: 1" in text

    def test_pdf_no_skipped_files_message_when_filewise(self, sample_file_stats, tmp_path):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        output = tmp_path / "report.pdf"

        generate_pdf(summary, percentages, output, skipped=[], filewise=True)

        from pypdf import PdfReader
        text = PdfReader(str(output)).pages[0].extract_text()
        assert "No files were skipped." in text

    def test_pdf_omits_skipped_section_by_default(self, sample_file_stats, tmp_path):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        output = tmp_path / "report.pdf"
        skipped = [("weird.exe", None, "unsupported file type")]

        generate_pdf(summary, percentages, output, repo_label="repo", skipped=skipped)  # filewise defaults to False

        from pypdf import PdfReader
        text = PdfReader(str(output)).pages[0].extract_text()
        assert "Skipped Files" not in text
        assert "Validated Files" not in text


class TestRuntimeColumnInTable:
    def test_format_table_without_runtimes_has_no_runtime_column(self, sample_file_stats):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        table = format_table(summary, percentages)  # runtimes=None (default)
        assert "Runtime" not in table

    def test_format_table_with_runtimes_shows_column(self, sample_file_stats):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        runtimes = {"Python": "Python 3.11.0", "Go": None}
        table = format_table(summary, percentages, runtimes=runtimes)
        assert "Runtime" in table
        assert "Python 3.11.0" in table
        assert "-" in table  # Go's None renders as a dash


class TestAwsSdkColumnInTable:
    def test_format_table_without_aws_sdk_info_has_no_column(self, sample_file_stats):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        table = format_table(summary, percentages)  # aws_sdk_info=None (default)
        assert "AWS SDK" not in table

    def test_format_table_with_aws_sdk_info_shows_column(self, sample_file_stats):
        from src.aws_sdk import AwsSdkInfo

        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        aws_sdk_info = {
            "Python": AwsSdkInfo(sdk="boto3 1.34.100", manifest="requirements.txt"),
            "Go": None,
        }
        table = format_table(summary, percentages, aws_sdk_info=aws_sdk_info)
        assert "AWS SDK" in table
        assert "Manifest" in table
        assert "boto3 1.34.100" in table
        assert "requirements.txt" in table
        assert "-" in table  # Go's None renders as a dash in both columns

    def test_runtime_and_aws_sdk_columns_coexist(self, sample_file_stats):
        from src.aws_sdk import AwsSdkInfo

        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        runtimes = {"Python": "Python 3.11.0", "Go": None}
        aws_sdk_info = {"Python": AwsSdkInfo(sdk="boto3 1.34.100", manifest="requirements.txt"), "Go": None}
        table = format_table(summary, percentages, runtimes=runtimes, aws_sdk_info=aws_sdk_info)
        header_line = table.splitlines()[0]
        assert header_line.index("Runtime") < header_line.index("AWS SDK") < header_line.index("Manifest")


class TestRuntimeColumnInPdf:
    def test_pdf_without_runtimes_has_no_runtime_column(self, sample_file_stats, tmp_path):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        output = tmp_path / "report.pdf"
        generate_pdf(summary, percentages, output)  # runtimes=None (default)

        from pypdf import PdfReader
        text = PdfReader(str(output)).pages[0].extract_text()
        assert "Runtime" not in text

    def test_pdf_with_runtimes_shows_column(self, sample_file_stats, tmp_path):
        summary = aggregate(sample_file_stats)
        percentages = compute_percentages(summary)
        output = tmp_path / "report.pdf"
        runtimes = {"Python": "Python 3.11.0", "Go": None}
        generate_pdf(summary, percentages, output, runtimes=runtimes)

        from pypdf import PdfReader
        text = PdfReader(str(output)).pages[0].extract_text()
        assert "Runtime" in text
        assert "Python 3.11.0" in text
