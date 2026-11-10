# codestats

A command line tool that recursively scans a local repository and reports total
lines, code lines, comments, blank lines, file counts, and language composition
for **Java, Python, Go, Ruby, Rust, C, and C++**.

It provides terminal, JSON, and optional PDF reporting, with Git-aware file
discovery, incremental SQLite caching, runtime/project detection, AWS SDK
detection, configurable exclusions, and cross-platform Windows/Linux/macOS
support.

```text
 Language  Files  Lines  Code  Comments  Blanks
=================================================
 Java          6    575   412        72      91
 Python        8    430   301        50      79
 Go            3    180   140        15      25
 Rust          2     90    70         8      12
=================================================
 Total        19  1,275   923       145     207

[████████████████████░░░░░░░░░░░░░░░░░░]
● Java 45.2%  ● Python 33.0%  ● Go 15.4%  ● Rust 7.4%

Cache Summary
-------------
Cache file:      /tmp/codestats_cache_3f9a1c2b7e6d0451.db
Files reused:    13995 (100.0%)
Files rescanned: 0

Timing Breakdown
----------------
Files found:        15000
File discovery:     0.026s
Processing:         0.250s
Other (output etc): 0.000s
```

## Supported languages

| Language | Recognised extensions / filenames |
|---|---|
| Java | `.java` |
| Python | `.py`, `.pyw`, `.pyi` |
| Go | `.go` |
| Ruby | `.rb`, plus `Rakefile` / `Gemfile` |
| Rust | `.rs` |
| C | `.c`, `.h` |
| C++ | `.cpp`, `.cc`, `.cxx`, `.c++`, `.hpp`, `.hxx`, `.hh` |

Any unsupported file type, such as JavaScript, HTML, Markdown, JSON, images,
or binaries, is not counted.

Binary files are also skipped even if they have a supported source extension.

## AWS SDK detection

`--aws-sdk` adds AWS SDK and manifest information to the language summary.

```bash
codestats ~/projects/my-service --aws-sdk
```

```text
 Language  Files  Lines  Code  Comments  Blanks                AWS SDK     Manifest
=====================================================================================
 Python        1      2     2         0       0  boto3 1.34.100  requirements.txt
 Go           12    980   820        60     100  aws-sdk-go-v2 v1.30.0          go.mod
```

With `--json`, the payload also contains an `aws_sdk` object.

The detector reads project manifests instead of scanning every source file for
imports. Examples include:

| Language / ecosystem | Manifest files considered |
|---|---|
| Python | `requirements.txt`, `pyproject.toml`, `Pipfile` |
| JavaScript / TypeScript | `package.json` |
| Go | `go.mod` |
| Java / Kotlin | `pom.xml`, `build.gradle` |
| Ruby | `Gemfile` |
| C# / F# | `*.csproj` |
| Rust | `Cargo.toml` |
| C++ | `CMakeLists.txt` |

If no AWS SDK is detected, `-` is displayed.

## Runtime detection

`--runtime` reports the **declared** runtime/version requirement from project
manifest files. It does not report the runtime currently installed on the
machine.

```bash
codestats . --runtime
```

The detector considers project files such as:

```text
pom.xml
package.json
pyproject.toml
go.mod
Gemfile
Cargo.toml
*.csproj
.tool-versions
CMakeLists.txt
```

`--runtime` provides one runtime value per detected language using the
shallowest relevant manifest.

For repositories containing several independent projects with different
runtime versions, use `--projects`.

## Project detection

`--projects` finds distinct project roots in the scanned tree.

```bash
codestats . --projects
```

A project root is a directory containing a recognised project manifest such as:

```text
pom.xml
package.json
go.mod
pyproject.toml
Gemfile
Cargo.toml
*.csproj
CMakeLists.txt
```

This is useful for:

- Monorepos
- Multi-service repositories
- Repositories containing several applications
- Repositories where different projects use different runtime versions

The number of displayed projects is controlled by:

```text
CODESTATS_MAX_PROJECTS_DISPLAYED
```

Default:

```text
7
```

## Requirements

- **Python 3.8+**
- **Git** is optional. It is required for `--git`; without it, CodeStats can
  perform a normal filesystem scan.
- **ReportLab >= 4.0** for PDF generation.

The runtime dependency is installed automatically through `pyproject.toml`.

## Installation

### Basic installation

```bash
cd codestats
pip install -e .
```

This registers the `codestats` command.

Verify:

```bash
codestats --help
```

### Install dependencies manually

```bash
pip install -r requirements.txt
pip install -e .
```

### Development/test installation

```bash
pip install -r requirements-dev.txt
```

### Virtual environment

#### Windows PowerShell / CMD

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

#### Linux / macOS / WSL

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Windows-specific notes

The application behaves the same on Windows, Linux, and macOS. Only the path
syntax changes between shells.

| Shell | Example |
|---|---|
| PowerShell / cmd.exe | `codestats "C:\Users\me\Desktop\myproject"` |
| Git Bash | `codestats "/c/Users/me/Desktop/myproject"` |
| WSL | `codestats "/mnt/c/Users/me/Desktop/myproject"` |
| Linux/macOS | `codestats "/home/me/projects/myproject"` |

Always quote paths containing spaces.

## Usage

```bash
codestats [path] [options]
```

If `path` is omitted, the current directory is analyzed.

### Analyze the current directory

```bash
codestats
```

### Analyze a specific repository

```bash
codestats ~/projects/my-repo
```

Windows:

```powershell
codestats "C:\Users\me\projects\my-repo"
```

### Exclude directories/files

```bash
codestats . --exclude "tests/*"
```

Multiple exclusions:

```bash
codestats . --exclude "tests/*" --exclude "docs/*"
```

The option is repeatable.

Patterns are written using forward slashes internally, even on Windows.

### Git-aware scan

```bash
codestats . --git
```

This uses:

```bash
git ls-files
```

and respects `.gitignore`.

Without `--git`, CodeStats performs a filesystem walk.

### Sort by total lines

```bash
codestats . --sort-by lines
```

### Sort by code lines

```bash
codestats . --sort-by code
```

### Sort by file count

```bash
codestats . --sort-by files
```

### Sort by comments

```bash
codestats . --sort-by comment
```

### Sort by blanks

```bash
codestats . --sort-by blank
```

### JSON output

```bash
codestats . --json
```

JSON is machine-readable and contains the same core statistics as the terminal
report, plus optional sections when related flags are enabled.

For CI/CD, use:

```bash
codestats . --json --no-pdf
```

### Disable the language bar

```bash
codestats . --no-bar
```

### Disable terminal ANSI colors

```bash
codestats . --no-color
```

Useful when redirecting output:

```bash
codestats . --no-color > report.txt
```

### Generate a PDF

PDF generation is **not automatic**. Pass `--pdf` to generate one.

Use the default filename:

```bash
codestats . --pdf
```

Default filename:

```text
codestats_report.pdf
```

Use a custom filename:

```bash
codestats . --pdf "reports/q3_scan.pdf"
```

The destination directory must already exist.

### Per-file information

```bash
codestats . --filewise
```

This adds:

- Validated Files
- Skipped Files
- Per-file statistics

The information is included in terminal, JSON, and PDF output.

### Runtime information

```bash
codestats . --runtime
```

### Project roots

```bash
codestats . --projects
```

### AWS SDK information

```bash
codestats . --aws-sdk
```

### Custom cache database

```bash
codestats . --cache-file "C:\tmp\codestats.db"
```

Linux:

```bash
codestats . --cache-file "/tmp/codestats.db"
```

### Clear the cache

```bash
codestats . --cache-clear
```

This deletes the selected cache before scanning and forces all files to be
rescanned. The cache is populated again after the scan.

### Full analysis

```bash
codestats . \
  --git \
  --filewise \
  --runtime \
  --projects \
  --aws-sdk \
  --json \
  --pdf "codestats_report.pdf"
```

On PowerShell, the equivalent can be written as:

```powershell
codestats . --git --filewise --runtime --projects --aws-sdk --json --pdf "codestats_report.pdf"
```

## All command-line options

| Flag | Description | Default |
|---|---|---|
| `path` | Directory to analyze recursively | `.` |
| `--exclude PATTERN` | Glob pattern to exclude; repeatable | none |
| `--git` | Use `git ls-files` for discovery and respect `.gitignore` | off |
| `--sort-by {code,lines,files,comment,blank}` | Metric used for table sorting and percentages | `code` |
| `--json` | Output machine-readable JSON instead of terminal table | off |
| `--no-color` | Disable ANSI colors in the terminal language bar | off |
| `--no-bar` | Suppress terminal language bar | off |
| `--pdf [FILE]` | Generate PDF; optional filename/path | no PDF |
| `--filewise` | Include validated/skipped file tables and per-file data | off |
| `--runtime` | Show declared runtime/version from manifests | off |
| `--projects` | Show distinct project roots and their runtime information | off |
| `--aws-sdk` | Show declared AWS SDK dependency/version and manifest | off |
| `--cache-file PATH` | Use a specific SQLite cache database | auto-generated |
| `--cache-clear` | Delete cache before scanning and force a fresh scan | off |
| `--help` / `-h` | Show command help | — |

### `--pdf` behavior

`--pdf` accepts an optional value.

```bash
codestats . --pdf
```

uses:

```text
codestats_report.pdf
```

while:

```bash
codestats . --pdf report.pdf
```

uses:

```text
report.pdf
```

The default PDF filename can be changed with:

```text
CODESTATS_DEFAULT_PDF_FILENAME
```

There is **no `--no-pdf` option in the current CLI** because PDF generation is
already opt-in.

## Environment configuration

CodeStats supports an optional `.env` file.

The lookup order is:

1. `CODESTATS_ENV_FILE`, when set as a real environment variable.
2. `.env` in the current working directory.
3. Built-in defaults.

A real environment variable always takes precedence over `.env`.

### Example `.env`

```env
CODESTATS_DEFAULT_PDF_FILENAME=codestats_report.pdf
CODESTATS_WORKER_MEMORY_MB=300
CODESTATS_MIN_FILES_FOR_PARALLEL=1000
CODESTATS_EXTRA_IGNORE_DIRS=
CODESTATS_DEFAULT_SORT_BY=code
CODESTATS_MAX_PROJECTS_DISPLAYED=7

# Optional fixed cache:
# CODESTATS_CACHE_FILE=C:\tmp\codestats.db

# Optional cache directory:
# CODESTATS_CACHE_DIR=C:\tmp

# Optional external .env:
# CODESTATS_ENV_FILE=C:\config\codestats.env
```

### Environment parameters

| Variable | Default | Description |
|---|---:|---|
| `CODESTATS_DEFAULT_PDF_FILENAME` | `codestats_report.pdf` | Filename used by `--pdf` when no filename is supplied |
| `CODESTATS_WORKER_MEMORY_MB` | `300` | Assumed memory budget per worker for automatic parallelism |
| `CODESTATS_MIN_FILES_FOR_PARALLEL` | `1000` | Below this file count, scanning remains sequential |
| `CODESTATS_EXTRA_IGNORE_DIRS` | empty | Additional directory names to ignore; comma-separated |
| `CODESTATS_DEFAULT_SORT_BY` | `code` | Default sort metric |
| `CODESTATS_MAX_PROJECTS_DISPLAYED` | `7` | Maximum project roots shown by `--projects` |
| `CODESTATS_CACHE_FILE` | unset | Exact SQLite cache database path |
| `CODESTATS_CACHE_DIR` | OS-specific | Base directory for automatically named cache files |
| `CODESTATS_ENV_FILE` | `.env` | External environment-file path; must be supplied as a real environment variable |

### Configure the environment file

PowerShell:

```powershell
$env:CODESTATS_ENV_FILE="C:\config\codestats.env"
codestats .
```

Linux/macOS/WSL:

```bash
export CODESTATS_ENV_FILE=/opt/config/codestats.env
codestats .
```

### Configure extra ignored directories

```env
CODESTATS_EXTRA_IGNORE_DIRS=dist,.cache,generated
```

## Incremental scanning and cache

Caching is **always enabled**.

CodeStats stores file statistics in SQLite and reuses results for unchanged
files.

### First run

```bash
codestats .
```

The first scan normally has no reusable entries, so files are processed and
stored in the cache.

### Second run

```bash
codestats .
```

Files whose size and modification time are unchanged can be reused without
reading their contents again.

### Cache information

The terminal output includes a cache summary:

```text
Cache Summary
-------------
Cache file:      C:\tmp\codestats_cache_1104de2f4a1ed174.db
Files reused:    13995 (100.0%)
Files rescanned: 0
```

JSON includes a `cache` object.

### Default cache location

When `--cache-file` and `CODESTATS_CACHE_FILE` are not set:

- Windows: `C:\tmp`
- Linux/macOS/WSL: the operating-system temporary directory

The filename is generated from a hash of the resolved repository path, for
example:

```text
codestats_cache_1104de2f4a1ed174.db
```

Different repositories therefore get different cache files.

Nothing is written into the scanned repository by default.

### Fixed cache path

```bash
codestats . --cache-file "C:\tmp\codestats.db"
```

Or:

```env
CODESTATS_CACHE_FILE=C:\tmp\codestats.db
```

### Custom cache directory

```env
CODESTATS_CACHE_DIR=C:\tmp
```

`CODESTATS_CACHE_FILE` takes precedence over `CODESTATS_CACHE_DIR`.

### Clear the cache

```bash
codestats . --cache-clear
```

This forces a complete fresh scan and then repopulates the cache.
## Output formats

### Terminal

Normal output includes:

- Language
- Files
- Lines
- Code
- Comments
- Blanks
- Totals
- Language percentage bar
- Cache summary
- Timing breakdown

### JSON

```bash
codestats . --json
```

JSON is intended for:

- CI/CD pipelines;
- automation;
- scripts;
- dashboards;
- machine-readable reports.

Optional features add corresponding JSON sections:

```text
cache
timing
files
skipped
runtime
projects
aws_sdk
```

### PDF

```bash
codestats . --pdf
```

The PDF contains the repository statistics and, when requested, additional
file/runtime/AWS/project information.

## Invalid input and edge cases

| Scenario | Behavior |
|---|---|
| Path does not exist | `error: Path does not exist: <path>`, exit code `1` |
| Path is a file | `error: Path is not a directory: <path>`, exit code `1` |
| URL supplied instead of local path | Treated as a local path; clone the repository first |
| No recognised source files | Prints `No recognised source files found.`, exit code `0` |
| Binary file with supported extension | Skipped |
| Unsupported extension | Skipped |
| Missing Git with `--git` | Git discovery cannot be used; use normal filesystem scanning if Git is unavailable |
| PDF generation unavailable | Terminal/JSON information can still be produced; PDF generation reports a warning/error rather than affecting the core scan |

## Testing

Install development dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the complete test suite:

```bash
pytest -v
```

Run a specific test module:

```bash
pytest tests/test_languages.py -v
```

```bash
pytest tests/test_counter.py -v
```

```bash
pytest tests/test_walker.py -v
```

```bash
pytest tests/test_report.py -v
```

```bash
pytest tests/test_cli.py -v
```

```bash
pytest tests/test_cache.py -v
```

```bash
pytest tests/test_runtime.py -v
```

```bash
pytest tests/test_aws_sdk.py -v
```

```bash
pytest tests/test_config.py -v
```

Run a specific test:

```bash
pytest tests/test_cli.py::TestBuildParser::test_defaults -v
```

### Coverage

Install:

```bash
pip install pytest-cov
```

Run:

```bash
pytest --cov=codestats --cov-report=term-missing
```

Generate an HTML report:

```bash
pytest --cov=codestats --cov-report=html
```

The report is generated under:

```text
htmlcov/
```

## Project structure

```text
codestats/
├── codestats/
│   ├── __init__.py
│   ├── cli.py
│   ├── counter.py
│   ├── manifest_utils.py
│   ├── report.py
│   ├── aws_sdk.py
│   ├── config.py
│   ├── walker.py
│   ├── runtime.py
│   ├── languages.py
│   └── cache.py
├── tests/
│   ├── __init__.py
│   ├── test_cli.py
│   ├── test_aws_sdk.py
│   ├── test_languages.py
│   ├── test_counter.py
│   ├── test_config.py
│   ├── test_runtime.py
│   ├── test_cache.py
│   ├── test_report.py
│   └── test_walker.py
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
├── .gitlab-ci.yml
├── detailed_parameter.txt
└── README.md
```

## How it works

1. **Path validation** — the CLI validates and resolves the repository path,
   expands `~`, checks that it exists, and confirms it is a directory.
2. **File discovery** — `walker.get_files()` recursively discovers files.
   With `--git`, it uses `git ls-files`; otherwise it walks the filesystem.
3. **Language detection** — `languages.detect_language()` maps supported
   extensions/special filenames to the seven supported languages.
4. **Line counting** — `counter.count_file()` classifies source lines as
   blank, comment, or code and skips binary/unreadable files.
5. **Caching** — the SQLite cache checks file metadata and reuses unchanged
   results.
6. **Parallel processing** — large scans can use automatically sized worker
   processes.
7. **Aggregation** — `report.aggregate()` combines per-file statistics into
   language totals.
8. **Percentages** — `report.compute_percentages()` calculates the language
   composition using the selected sort metric.
9. **Optional manifest analysis** — `--runtime`, `--projects`, and `--aws-sdk`
   inspect recognised project manifests.
10. **Output** — terminal, JSON, and optional PDF reports are generated from
    the collected statistics.
11. **Timing/cache summary** — the scan ends with timing and cache information.
