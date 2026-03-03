# FormatEx Python SDK

[![PyPI version](https://img.shields.io/pypi/v/formatex)](https://pypi.org/project/formatex/)
[![Python](https://img.shields.io/pypi/pyversions/formatex)](https://pypi.org/project/formatex/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Official Python SDK for the [FormatEx](https://formatex.io) LaTeX-to-PDF API.

## Installation

```bash
pip install formatex
```

Requires Python ≥ 3.9.

## Quick Start

```python
from formatex import FormatExClient

with FormatExClient("fx_your_api_key") as client:
    result = client.compile(
        r"\documentclass{article}\begin{document}Hello, world!\end{document}"
    )
    # result.pdf          → bytes
    # result.engine       → "pdflatex"
    # result.duration_ms  → 412
    with open("output.pdf", "wb") as f:
        f.write(result.pdf)
```

Get an API key from the [FormatEx dashboard](https://app.formatex.io).

---

## Compilation

### Sync (immediate response)

```python
# Choose your engine
result = client.compile(latex, engine="pdflatex")   # default
result = client.compile(latex, engine="xelatex")    # Unicode + modern fonts
result = client.compile(latex, engine="lualatex")   # Lua scripting
result = client.compile(latex, engine="latexmk")    # automatic multi-pass

# Smart compile: auto-detects the right engine + attempts auto-fix
result = client.compile_smart(latex)

# Compile directly to a file
client.compile_to_file(latex, "output.pdf")
client.compile_to_file(latex, "output.pdf", engine="xelatex")
client.compile_to_file(latex, "output.pdf", smart=True)
```

### Async (long-running documents)

```python
with FormatExClient("fx_your_api_key") as client:
    # Submit and get a job ID immediately
    job = client.async_compile(latex, engine="pdflatex")
    print(job.job_id, job.status)  # "abc-123", "pending"

    # Option 1: blocking wait (polls automatically)
    result = client.wait_for_job(job.job_id)
    with open("output.pdf", "wb") as f:
        f.write(result.pdf)

    # Option 2: manual polling loop
    import time
    while True:
        status = client.get_job(job.job_id)
        if status.status == "completed":
            pdf = client.get_job_pdf(job.job_id)  # one-time download
            break
        elif status.status == "failed":
            print("Failed:", status.error)
            break
        time.sleep(2)

    # Retrieve just the log
    log = client.get_job_log(job.job_id)

    # Clean up server-side (optional — PDF auto-deletes after download)
    client.delete_job(job.job_id)
```

---

## Multi-File Projects

Use `file_entry` to attach companion files (images, `.bib`, `.cls`, etc.):

```python
from pathlib import Path
from formatex import FormatExClient, file_entry

latex = r"""
\documentclass{article}
\usepackage{graphicx}
\begin{document}
\includegraphics[width=\linewidth]{logo.png}
\bibliography{refs}
\end{document}
"""

with FormatExClient("fx_your_api_key") as client:
    result = client.compile(
        latex,
        engine="pdflatex",
        files=[
            file_entry("logo.png", Path("assets/logo.png")),   # auto-read from disk
            file_entry("refs.bib", Path("references.bib")),
        ],
    )
    Path("output.pdf").write_bytes(result.pdf)
```

`file_entry(name, content)` accepts:
- `Path` — reads the file automatically
- `bytes` — raw binary data, base64-encoded for you
- `str` — already base64-encoded content passed through as-is

---

## Lint (Static Analysis)

Runs `chktex` without consuming compilation quota:

```python
with FormatExClient("fx_your_api_key") as client:
    result = client.lint(latex)

    print(f"Valid: {result.valid}")
    print(f"Errors: {result.error_count}, Warnings: {result.warning_count}")

    for d in result.diagnostics:
        print(f"  Line {d.line}:{d.column} [{d.severity}] {d.message}")
```

Integrate into CI:

```python
result = client.lint(source)
if not result.valid:
    raise SystemExit(f"LaTeX lint failed: {result.error_count} error(s)")
```

---

## Convert to Word (DOCX)

```python
with FormatExClient("fx_your_api_key") as client:
    result = client.convert(latex)
    Path("document.docx").write_bytes(result.docx)

    # Or write directly to a file
    client.convert_to_file(latex, "document.docx")
```

---

## Syntax Check

Free endpoint — does not count against your quota:

```python
check = client.check_syntax(latex)
print(check.valid, check.errors)
```

---

## Usage Stats & Engines

```python
usage = client.get_usage()
print(f"{usage.compilations_used}/{usage.compilations_limit} compilations this month")
print(f"Overage: {usage.overage}")

engines = client.list_engines()
for e in engines:
    print(e["name"], e["available"])
```

---

## Error Handling

```python
from formatex import (
    FormatExClient,
    AuthenticationError,
    CompilationError,
    RateLimitError,
    PlanLimitError,
)

with FormatExClient("fx_your_api_key") as client:
    try:
        result = client.compile(latex)
    except AuthenticationError:
        print("Invalid API key")
    except CompilationError as e:
        print(f"Compilation failed: {e}")
        print(f"Compiler log:\n{e.log}")
    except RateLimitError as e:
        print(f"Rate limited — retry after {e.retry_after}s")
    except PlanLimitError:
        print("Plan limit exceeded — upgrade at https://app.formatex.io/billing")
```

---

## Type Reference

All types are importable directly from `formatex`:

| Type | Description |
|------|-------------|
| `CompileResult` | Sync compile result: `pdf`, `engine`, `duration_ms`, `size_bytes`, `log`, `job_id` |
| `AsyncJob` | Submitted async job: `job_id`, `status` |
| `JobResult` | Polled job state: `job_id`, `status`, `log`, `duration_ms`, `error`, `success` |
| `LintResult` | Lint output: `diagnostics`, `duration_ms`, `error_count`, `warning_count`, `valid` |
| `LintDiagnostic` | Single finding: `line`, `column`, `severity`, `message`, `source`, `code` |
| `SyntaxResult` | Syntax check: `valid`, `errors` |
| `ConvertResult` | DOCX output: `docx` (bytes), `size_bytes` |
| `UsageStats` | Quota: `compilations_used`, `compilations_limit`, `overage`, `period_start`, `period_end` |

---

## Links

- [FormatEx Website](https://formatex.io)
- [API Documentation](https://formatex.io/docs/api)
- [Dashboard](https://app.formatex.io)
- [Status](https://formatex.io/status)

## License

MIT
