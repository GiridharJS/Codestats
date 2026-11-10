"""Aggregates per-file FileStats into a per-language summary, computes
percentages, and renders the results both as a terminal table + bar
and as a downloadable PDF report.
"""

from collections import defaultdict
from pathlib import Path

BAR_CHARS = "█"
# A fixed palette cycled through for the language bar / legend, using
# ANSI 256-colour codes so it's colourful without extra dependencies.
ANSI_PALETTE = [33, 208, 34, 197, 45, 220, 129, 202, 27, 82, 172, 63]
RESET = "\033[0m"

# One fixed hex colour per supported language, used consistently
# between the terminal bar (converted to nearest ANSI) and the PDF.
LANGUAGE_HEX_COLORS = {
    "Java": "#B07219",
    "Python": "#3572A5",
    "Go": "#00ADD8",
    "Ruby": "#701516",
    "Rust": "#DEA584",
    "C": "#555555",
    "C++": "#F34B7D",
}
DEFAULT_HEX_PALETTE = ["#185FA5", "#0F6E56", "#534AB7", "#993C1D", "#993556", "#5F5E5A", "#D99A3D"]


def _color_for(lang, index):
    return LANGUAGE_HEX_COLORS.get(lang, DEFAULT_HEX_PALETTE[index % len(DEFAULT_HEX_PALETTE)])


def aggregate(file_stats_list):
    """Turn a list of FileStats (some possibly None) into a dict:
    {language: {"files": n, "lines": n, "blank": n, "comment": n, "code": n}}
    """
    summary = defaultdict(lambda: {"files": 0, "lines": 0, "blank": 0, "comment": 0, "code": 0})
    for fs in file_stats_list:
        if fs is None or fs.language is None:
            continue
        bucket = summary[fs.language]
        bucket["files"] += 1
        bucket["lines"] += fs.lines
        bucket["blank"] += fs.blank
        bucket["comment"] += fs.comment
        bucket["code"] += fs.code
    return dict(summary)


def compute_percentages(summary, key="code"):
    """Return {language: percentage} based on the given metric key
    (default 'code'). Percentages sum to ~100 across all languages.
    """
    total = sum(bucket[key] for bucket in summary.values())
    if total == 0:
        return {lang: 0.0 for lang in summary}
    return {lang: (bucket[key] / total) * 100 for lang, bucket in summary.items()}


def totals(summary):
    """Return a single dict with grand totals across all languages."""
    out = {"files": 0, "lines": 0, "blank": 0, "comment": 0, "code": 0}
    for bucket in summary.values():
        for k in out:
            out[k] += bucket[k]
    return out


def sorted_languages(summary, sort_by="code"):
    """Return language names sorted descending by the given metric."""
    return sorted(summary.keys(), key=lambda lang: summary[lang][sort_by], reverse=True)


def format_table(summary, percentages, sort_by="code", runtimes=None, aws_sdk_info=None):
    """Plain-text per-language table, styled like tokei's own output:
    right-aligned numeric columns, "===" rules under the header and
    above the total. `runtimes` adds a "Runtime" column. `aws_sdk_info`
    (a {language: AwsSdkInfo} dict) adds "AWS SDK" and "Manifest"
    columns. One row per language, no nested sub-rows.
    """
    if not summary:
        return "No recognised source files found."

    langs = sorted_languages(summary, sort_by)
    show_runtime = runtimes is not None
    show_aws_sdk = aws_sdk_info is not None

    headers = ["Language", "Files", "Lines", "Code", "Comments", "Blanks"]
    if show_runtime:
        headers.append("Runtime")
    if show_aws_sdk:
        headers.append("AWS SDK")
        headers.append("Manifest")
    ncols = len(headers)
    # Language stays left-aligned; every numeric column (and the
    # trailing Runtime/AWS SDK/Manifest columns, which are text but
    # read better right-aligned like tokei's own extra columns) is
    # right-aligned.
    left_aligned = {0}

    rows = []
    for lang in langs:
        b = summary[lang]
        row = [
            lang,
            str(b["files"]),
            f"{b['lines']:,}",
            f"{b['code']:,}",
            f"{b['comment']:,}",
            f"{b['blank']:,}",
        ]
        if show_runtime:
            row.append(runtimes.get(lang) or "-")
        if show_aws_sdk:
            info = aws_sdk_info.get(lang)
            row.append(info.sdk if info else "-")
            row.append(info.manifest if info else "-")
        rows.append(row)

    t = totals(summary)
    grand_total_row = [
        "Total",
        str(t["files"]),
        f"{t['lines']:,}",
        f"{t['code']:,}",
        f"{t['comment']:,}",
        f"{t['blank']:,}",
    ]
    if show_runtime:
        grand_total_row.append("")
    if show_aws_sdk:
        grand_total_row.append("")
        grand_total_row.append("")

    widths = [len(h) for h in headers]
    for row in rows:
        for i in range(ncols):
            widths[i] = max(widths[i], len(row[i]))
    for i in range(ncols):
        widths[i] = max(widths[i], len(grand_total_row[i]))

    def fmt_row(row):
        cells = [
            row[i].ljust(widths[i]) if i in left_aligned else row[i].rjust(widths[i])
            for i in range(ncols)
        ]
        return " " + "  ".join(cells)

    rule_width = len(fmt_row(headers))
    heavy_rule = "=" * rule_width

    lines = [fmt_row(headers), heavy_rule]
    for row in rows:
        lines.append(fmt_row(row))
    lines.append(heavy_rule)
    lines.append(fmt_row(grand_total_row))
    return "\n".join(lines)


def format_bar(percentages, sort_by_summary=None, width=40, use_color=True):
    """Render a GitHub-style horizontal language bar plus a legend."""
    if not percentages:
        return ""

    langs = sorted(percentages.keys(), key=lambda l: percentages[l], reverse=True)

    bar_segments = []
    legend_lines = []
    allocated = 0
    for i, lang in enumerate(langs):
        pct = percentages[lang]
        seg_width = round((pct / 100) * width)
        if i == len(langs) - 1:
            seg_width = max(width - allocated, 0)
        allocated += seg_width

        color_code = ANSI_PALETTE[i % len(ANSI_PALETTE)]
        segment = BAR_CHARS * seg_width
        if use_color:
            segment = f"\033[38;5;{color_code}m{segment}{RESET}"
        bar_segments.append(segment)

        legend_entry = f"{lang} {pct:.1f}%"
        if use_color:
            legend_entry = f"\033[38;5;{color_code}m●{RESET} {legend_entry}"
        else:
            legend_entry = f"* {legend_entry}"
        legend_lines.append(legend_entry)

    bar = "[" + "".join(bar_segments) + "]"
    legend = "  ".join(legend_lines)
    return f"{bar}\n{legend}"


def format_files_table(file_stats):
    """Render a plain-text table listing every individual file that
    was successfully analysed -- file name, detected language, and
    its line breakdown -- mirroring the style of the skipped-files
    table. `file_stats` is a list of counter.FileStats.
    """
    if not file_stats:
        return "Validated files: 0"

    headers = ["File Name", "Language", "Lines", "Code", "Comments", "Blank"]
    rows = []
    for fs in file_stats:
        rows.append([
            fs.path, fs.language, f"{fs.lines:,}", f"{fs.code:,}",
            f"{fs.comment:,}", f"{fs.blank:,}",
        ])

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(row):
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    sep = "-" * (sum(widths) + 2 * (len(widths) - 1))

    lines = ["Validated Files", sep, fmt_row(headers), sep]
    for row in rows:
        lines.append(fmt_row(row))
    lines.append(sep)
    lines.append(f"Total validated: {len(file_stats)}")
    return "\n".join(lines)


def format_cache_summary(cache_info):
    """Render a short summary of a scan's cache usage: how many files
    were reused straight from the SQLite cache vs. actually re-read.
    """
    hits = cache_info["cache_hits"]
    misses = cache_info["cache_misses"]
    total = hits + misses
    hit_pct = (hits / total * 100) if total else 0.0

    lines = [
        "Cache Summary",
        "-------------",
        f"Cache file:      {cache_info['cache_file']}",
        f"Files reused:    {hits} ({hit_pct:.1f}%)",
        f"Files rescanned: {misses}",
    ]

    return "\n".join(lines)


def format_timing_summary(timing_info):
    """Breakdown of where scan time went. Always shown, same as the
    cache summary.

    Discovery vs processing point at different causes when slow:
    discovery (walking the tree / git ls-files) being slow means a
    huge tree or slow gitignore matching, and --git might help.
    Processing being slow on a mostly-cache-hit run points at stat()
    itself being expensive -- antivirus, a cloud-synced folder, or a
    network drive, not anything this code is doing.

    workers_used shows what auto-detection actually picked for this
    run -- 1 worker on a big repo on a many-core machine points at
    auto-detection under-provisioning, not slow per-file work.
    """
    lines = [
        "Timing Breakdown",
        "----------------",
        f"Files found:        {timing_info['files_found']}",
        f"Workers used:       {timing_info['workers_used']}",
        f"File discovery:     {timing_info['discovery_seconds']:.3f}s",
        f"Processing:         {timing_info['processing_seconds']:.3f}s",
        f"Other (output etc): {timing_info['other_seconds']:.3f}s",
    ]
    return "\n".join(lines)


def format_projects_table(project_roots, total_found=None):
    """Table of discovered project roots (see find_project_roots):
    one row per (root, language) pair, showing each sub-project's own
    runtime -- surfaces monorepo structure that --runtime's single
    summary column can't (it only shows one, shallowest, answer per
    language).

    If total_found > len(project_roots), the list was capped -- a
    footer note says so.
    """
    if not project_roots:
        return "No recognised project manifests found."

    headers = ["Project Root", "Language", "Declared Runtime"]
    rows = []
    for entry in project_roots:
        root = entry["root"]
        for language in sorted(entry["languages"]):
            rows.append([root, language, entry["languages"][language]])

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(row):
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    sep = "-" * (sum(widths) + 2 * (len(widths) - 1))

    lines = ["Detected Project Roots", sep, fmt_row(headers), sep]
    for row in rows:
        lines.append(fmt_row(row))
    lines.append(sep)
    shown = len(project_roots)
    if total_found is not None and total_found > shown:
        lines.append(f"Showing {shown} of {total_found} projects found (shallowest first).")
        lines.append("Raise CODESTATS_MAX_PROJECTS_DISPLAYED in a .env file to see more.")
    else:
        lines.append(f"Total projects found: {shown}")
    return "\n".join(lines)


def format_skipped_table(skipped):
    """Render a plain-text table of skipped files (file name, detected
    language if any, and the reason they were not counted), with a
    trailing total count line. `skipped` is a list of
    (path_str, language_or_None, reason_str) tuples.
    """
    if not skipped:
        return "Skipped files: 0"

    headers = ["File Name", "Language", "Reason"]
    rows = [[path, lang or "-", reason] for path, lang, reason in skipped]

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(row):
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    sep = "-" * (sum(widths) + 2 * (len(widths) - 1))

    lines = ["Skipped Files", sep, fmt_row(headers), sep]
    for row in rows:
        lines.append(fmt_row(row))
    lines.append(sep)
    lines.append(f"Total skipped: {len(skipped)}")
    return "\n".join(lines)


def generate_pdf(summary, percentages, output_path, repo_label="", sort_by="code", skipped=None, file_stats=None, filewise=False, runtimes=None, aws_sdk_info=None):
    """Render the same data as format_table/format_bar into a PDF
    file at output_path. Requires the optional 'reportlab' dependency
    (pip install reportlab) -- raises ImportError with a clear message
    if it isn't installed, rather than failing obscurely.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        )
    except ImportError as exc:
        raise ImportError(
            "PDF output requires the 'reportlab' package. "
            "Install it with: pip install reportlab"
        ) from exc

    output_path = Path(output_path)
    doc = SimpleDocTemplate(
        str(output_path), pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        "CodestatsTitle", parent=styles["Title"], textColor=colors.HexColor("#26215C"),
    )
    story.append(Paragraph("codestats — Code Analysis Report", title_style))
    if repo_label:
        story.append(Paragraph(f"Repository: {repo_label}", styles["Normal"]))
    story.append(Spacer(1, 14))

    if not summary:
        story.append(Paragraph("No recognised source files found.", styles["Normal"]))
        if filewise:
            story.append(Spacer(1, 18))
            story.append(Paragraph("Validated Files", styles["Heading2"]))
            story.append(Spacer(1, 6))
            story.append(Paragraph("No files were validated.", styles["Normal"]))
            story.append(Spacer(1, 18))
            story.append(Paragraph("Skipped Files", styles["Heading2"]))
            story.append(Spacer(1, 6))
            skipped = skipped or []
            if not skipped:
                story.append(Paragraph("No files were skipped.", styles["Normal"]))
            else:
                story.append(Paragraph(f"<b>Total skipped:</b> {len(skipped)}", styles["Normal"]))
        doc.build(story)
        return output_path

    langs = sorted_languages(summary, sort_by)
    t = totals(summary)

    # ---- summary table ----
    show_runtime = runtimes is not None
    show_aws_sdk = aws_sdk_info is not None
    header = ["Language", "Files", "Lines", "Code", "Comments", "Blank", "%"]
    if show_runtime:
        header.append("Runtime")
    if show_aws_sdk:
        header.append("AWS SDK")
        header.append("Manifest")
    rows = [header]
    for lang in langs:
        b = summary[lang]
        row = [
            lang, str(b["files"]), f"{b['lines']:,}", f"{b['code']:,}",
            f"{b['comment']:,}", f"{b['blank']:,}", f"{percentages[lang]:.1f}%",
        ]
        if show_runtime:
            row.append(runtimes.get(lang) or "-")
        if show_aws_sdk:
            info = aws_sdk_info.get(lang)
            row.append(info.sdk if info else "-")
            row.append(info.manifest if info else "-")
        rows.append(row)
    total_row = [
        "TOTAL", str(t["files"]), f"{t['lines']:,}", f"{t['code']:,}",
        f"{t['comment']:,}", f"{t['blank']:,}", "100.0%",
    ]
    if show_runtime:
        total_row.append("")
    if show_aws_sdk:
        total_row.append("")
        total_row.append("")
    rows.append(total_row)

    table = Table(rows, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#26215C")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EEEEEE")),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F5F5")]),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 22))

    # ---- language composition bar (stacked, proportional widths) ----
    story.append(Paragraph("Language Composition", styles["Heading2"]))
    story.append(Spacer(1, 6))

    bar_total_width = 6.3  # inches, fits within letter page margins
    col_widths = []
    bar_style_cmds = [
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]
    for i, lang in enumerate(langs):
        pct = percentages[lang]
        w = max(pct / 100 * bar_total_width, 0.04)
        col_widths.append(w * inch)
        bar_style_cmds.append(("BACKGROUND", (i, 0), (i, 0), colors.HexColor(_color_for(lang, i))))

    bar_table = Table([[""] * len(langs)], colWidths=col_widths, rowHeights=[16])
    bar_table.setStyle(TableStyle(bar_style_cmds))
    story.append(bar_table)
    story.append(Spacer(1, 10))

    # ---- legend ----
    for i, lang in enumerate(langs):
        hexcolor = _color_for(lang, i)
        legend_text = (
            f'<font color="{hexcolor}">\u25CF</font> '
            f'<b>{lang}</b> — {percentages[lang]:.1f}%'
        )
        story.append(Paragraph(legend_text, styles["Normal"]))
        story.append(Spacer(1, 2))

    # ---- validated files + skipped files (only when filewise=True) ----
    if filewise:
        story.append(Spacer(1, 22))
        story.append(Paragraph("Validated Files", styles["Heading2"]))
        story.append(Spacer(1, 6))

        file_stats = file_stats or []
        if not file_stats:
            story.append(Paragraph("No files were validated.", styles["Normal"]))
        else:
            file_path_style = ParagraphStyle(
                "ValidatedPath", parent=styles["Normal"], fontSize=8.5, leading=10.5,
            )
            file_rows = [["File Name", "Language", "Lines", "Code", "Comments", "Blank"]]
            for fs in file_stats:
                file_rows.append([
                    Paragraph(fs.path, file_path_style), fs.language,
                    f"{fs.lines:,}", f"{fs.code:,}", f"{fs.comment:,}", f"{fs.blank:,}",
                ])

            files_table = Table(file_rows, repeatRows=1, hAlign="LEFT",
                                 colWidths=[2.8 * inch, 0.8 * inch, 0.65 * inch, 0.65 * inch, 0.85 * inch, 0.65 * inch])
            files_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#26215C")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
                ("ALIGN", (2, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(files_table)
            story.append(Spacer(1, 8))
            story.append(Paragraph(f"<b>Total validated:</b> {len(file_stats)}", styles["Normal"]))

        story.append(Spacer(1, 22))
        story.append(Paragraph("Skipped Files", styles["Heading2"]))
        story.append(Spacer(1, 6))

        skipped = skipped or []
        if not skipped:
            story.append(Paragraph("No files were skipped.", styles["Normal"]))
        else:
            path_style = ParagraphStyle(
                "SkippedPath", parent=styles["Normal"], fontSize=8.5, leading=10.5,
            )
            skip_rows = [["File Name", "Language", "Reason"]]
            for path, lang, reason in skipped:
                skip_rows.append([
                    Paragraph(path, path_style),
                    Paragraph(lang or "-", path_style),
                    Paragraph(reason, path_style),
                ])

            skip_table = Table(skip_rows, repeatRows=1, hAlign="LEFT",
                                colWidths=[3.9 * inch, 1.0 * inch, 1.4 * inch])
            skip_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#5F5E5A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9.5),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(skip_table)
            story.append(Spacer(1, 8))
            story.append(Paragraph(f"<b>Total skipped:</b> {len(skipped)}", styles["Normal"]))

    doc.build(story)
    return output_path
