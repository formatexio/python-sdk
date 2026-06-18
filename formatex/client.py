"""FormaTex Python client."""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from formatex._http import HTTPClient
from formatex.exceptions import FormaTexError

DEFAULT_BASE_URL = os.environ.get("FORMATEX_BASE_URL", "https://api.formatex.io")

# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class CompileResult:
    """Result of a synchronous compilation request."""

    pdf: bytes
    engine: str
    duration_ms: int
    size_bytes: int
    job_id: str
    log: str = ""
    analysis: dict | None = None  # present only for smart compile


@dataclass
class AsyncJob:
    """Reference to an async compilation job (returned immediately on submit)."""

    job_id: str
    status: str  # pending | processing | completed | failed


@dataclass
class JobResult:
    """Full status of a polled async job."""

    job_id: str
    status: str       # pending | processing | completed | failed
    log: str = ""
    duration_ms: int = 0
    error: str = ""
    success: bool = False


@dataclass
class LintDiagnostic:
    """A single lint issue reported by ChkTeX."""

    line: int
    column: int
    severity: str     # error | warning | info
    message: str
    source: str = "chktex"
    code: str = ""


@dataclass
class LintResult:
    """Result of a lint operation."""

    diagnostics: list[LintDiagnostic]
    duration_ms: int
    error_count: int = field(init=False)
    warning_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.error_count = sum(1 for d in self.diagnostics if d.severity == "error")
        self.warning_count = sum(1 for d in self.diagnostics if d.severity == "warning")

    @property
    def valid(self) -> bool:
        return self.error_count == 0


@dataclass
class SyntaxResult:
    """Result of a fast syntax check (no quota cost)."""

    valid: bool
    errors: list[dict]
    warnings: list[dict]


@dataclass
class ConvertResult:
    """Result of a LaTeX → DOCX conversion."""

    docx: bytes
    size_bytes: int


@dataclass
class UsageStats:
    """Monthly usage statistics."""

    plan: str
    compilations_used: int
    compilations_limit: int
    period_start: str
    period_end: str
    overage: int
    raw: dict


@dataclass
class RenderResult:
    """Result of a single equation render (or one item in a batch)."""

    data: bytes    # raw PNG or SVG bytes; empty when ``error`` is set
    format: str    # "png" or "svg"
    width: int     # pixels (0 if unknown)
    height: int    # pixels (0 if unknown)
    error: str = ""  # non-empty only for failed items in a batch


@dataclass
class Project:
    """A FormaTeX project."""

    id: str
    name: str
    main_file: str
    file_count: int
    created_at: str
    updated_at: str
    raw: dict


@dataclass
class ProjectFile:
    """Metadata for a single file inside a project."""

    path: str
    size: int
    mime_type: str
    updated_at: str
    raw: dict


@dataclass
class WordCountResult:
    """Word and structure counts from a LaTeX document (via texcount)."""

    text_words: int
    header_words: int
    caption_words: int
    headers: int
    floats: int
    math_inline: int
    math_display: int
    total_words: int
    duration_ms: int


@dataclass
class DependenciesResult:
    """Package dependency analysis for a LaTeX document."""

    packages: list[str]        # all packages declared in the document
    available: list[str]       # packages found in TeX Live
    unavailable: list[str]     # packages not found in TeX Live
    duration_ms: int


@dataclass
class PackageStatus:
    """Availability of a single TeX package."""

    name: str
    available: bool


@dataclass
class DocumentMetadata:
    """Extracted metadata from a LaTeX document."""

    title: str
    authors: list[str]
    date: str
    abstract: str
    keywords: list[str]


@dataclass
class BibFormatted:
    """Pre-formatted citation strings for a single BibTeX entry."""

    apa: str
    mla: str
    chicago: str


@dataclass
class BibEntry:
    """A single parsed BibTeX entry."""

    key: str
    type: str                   # article, book, inproceedings, etc.
    fields: dict[str, str]      # all field key-value pairs
    authors: list[str]          # split author/editor names
    formatted: BibFormatted     # APA, MLA, Chicago citations


@dataclass
class BibResult:
    """Result of a bibliography parse operation."""

    entries: list[BibEntry]
    count: int
    duration_ms: int


# ── Helper ────────────────────────────────────────────────────────────────────


def file_entry(name: str, content: bytes | str | Path) -> dict:
    """Build a companion-file entry for multi-file compilation.

    Args:
        name: Filename as it appears in the LaTeX source (e.g. ``"fig.png"``).
        content: Raw bytes, a file path, or an already-encoded base64 string.

    Returns:
        ``{"name": name, "content": "<base64>"}`` dict for the ``files`` list.

    Example::

        result = client.compile(
            latex,
            files=[
                file_entry("logo.png", Path("assets/logo.png")),
                file_entry("refs.bib", open("refs.bib", "rb").read()),
            ],
        )
    """
    if isinstance(content, Path):
        content = content.read_bytes()
    if isinstance(content, bytes):
        content = base64.b64encode(content).decode()
    return {"name": name, "content": content}


# ── Client ────────────────────────────────────────────────────────────────────


class FormaTexClient:
    """High-level client for the FormaTex LaTeX-to-PDF API.

    Initialise with an API key obtained from the dashboard::

        from formatex import FormaTexClient

        client = FormaTexClient("fx_your_api_key")

    Use as a context manager to ensure the underlying HTTP connection is closed::

        with FormaTexClient("fx_your_api_key") as client:
            result = client.compile(r"\\documentclass{article}...")
            Path("out.pdf").write_bytes(result.pdf)
    """

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 120.0,
    ):
        self._http = HTTPClient(api_key=api_key, base_url=DEFAULT_BASE_URL, timeout=timeout)

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    def __enter__(self) -> "FormaTexClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── Sync Compilation ──────────────────────────────────────────────────────

    def compile(
        self,
        latex: str,
        *,
        engine: str = "pdflatex",
        timeout: int | None = None,
        runs: int | None = None,
        files: list[dict] | None = None,
    ) -> CompileResult:
        """Compile LaTeX source to PDF synchronously.

        Blocks until the PDF is ready (or raises on error).
        For large documents use :meth:`async_compile` + :meth:`wait_for_job`.

        Args:
            latex: LaTeX source code.
            engine: ``pdflatex`` (default), ``xelatex``, ``lualatex``, or ``latexmk``.
            timeout: Max compile time in seconds (plan-limited).
            runs: Number of compiler passes (1–5).
            files: Companion files (images, .bib, etc.) — use :func:`file_entry`
                   to build entries.

        Returns:
            :class:`CompileResult` with ``.pdf`` bytes and metadata.

        Raises:
            :class:`~FormaTex.CompilationError`: LaTeX errors in source.
            :class:`~FormaTex.PlanLimitError`: Monthly quota or plan restriction.
            :class:`~FormaTex.AuthenticationError`: Invalid API key.
        """
        body: dict[str, Any] = {"latex": latex, "engine": engine}
        if timeout is not None:
            body["timeout"] = timeout
        if runs is not None:
            body["runs"] = runs
        if files:
            body["files"] = files

        data = self._http.post_json("/api/v1/compile", body)
        return CompileResult(
            pdf=base64.b64decode(data["pdf"]),
            engine=data.get("engine", engine),
            duration_ms=data.get("duration", 0),
            size_bytes=data.get("sizeBytes", 0),
            job_id=data.get("jobId", ""),
            log=data.get("log", ""),
        )

    def compile_smart(
        self,
        latex: str,
        *,
        timeout: int | None = None,
        files: list[dict] | None = None,
    ) -> CompileResult:
        """Smart compile — auto-detects the required engine from the preamble.

        Inspects ``\\usepackage`` declarations to pick the best engine
        automatically (e.g. ``fontspec`` → xelatex, ``luacode`` → lualatex).

        Args:
            latex: LaTeX source code.
            timeout: Max compile time in seconds.
            files: Companion files — use :func:`file_entry`.

        Returns:
            :class:`CompileResult` with ``.analysis`` dict describing detected engine.
        """
        body: dict[str, Any] = {"latex": latex, "engine": "auto"}
        if timeout is not None:
            body["timeout"] = timeout
        if files:
            body["files"] = files

        data = self._http.post_json("/api/v1/compile/smart", body)
        return CompileResult(
            pdf=base64.b64decode(data["pdf"]),
            engine=data.get("engine", "auto"),
            duration_ms=data.get("duration", 0),
            size_bytes=data.get("sizeBytes", 0),
            job_id=data.get("jobId", ""),
            log=data.get("log", ""),
            analysis=data.get("analysis"),
        )

    def compile_to_file(
        self,
        latex: str,
        output_path: str | Path,
        *,
        engine: str = "pdflatex",
        smart: bool = False,
        **kwargs: Any,
    ) -> CompileResult:
        """Compile and write the PDF directly to a file.

        Args:
            latex: LaTeX source code.
            output_path: Destination path for the PDF (created/overwritten).
            engine: Engine to use (ignored when ``smart=True``).
            smart: Use :meth:`compile_smart` instead of :meth:`compile`.
            **kwargs: Forwarded to the underlying compile call.

        Returns:
            :class:`CompileResult` (same as compile).
        """
        result = self.compile_smart(latex, **kwargs) if smart else self.compile(latex, engine=engine, **kwargs)
        Path(output_path).write_bytes(result.pdf)
        return result

    # ── Async Compilation ─────────────────────────────────────────────────────

    def async_compile(
        self,
        latex: str,
        *,
        engine: str = "pdflatex",
        timeout: int | None = None,
        runs: int | None = None,
        files: list[dict] | None = None,
    ) -> AsyncJob:
        """Submit a compilation job to the background queue.

        Returns immediately with a job ID. Poll :meth:`get_job` to check
        progress, or use :meth:`wait_for_job` to block until done.

        Pro/max/entreprise plans get priority queue access.

        Args:
            latex: LaTeX source code.
            engine: Compilation engine.
            timeout: Max compile time in seconds.
            runs: Number of compiler passes.
            files: Companion files — use :func:`file_entry`.

        Returns:
            :class:`AsyncJob` with ``job_id`` and initial ``status="pending"``.
        """
        body: dict[str, Any] = {"latex": latex, "engine": engine}
        if timeout is not None:
            body["timeout"] = timeout
        if runs is not None:
            body["runs"] = runs
        if files:
            body["files"] = files

        data = self._http.post_json("/api/v1/compile/async", body)
        return AsyncJob(job_id=data["jobId"], status=data.get("status", "pending"))

    def get_job(self, job_id: str) -> JobResult:
        """Poll the status of an async compilation job.

        Args:
            job_id: ID returned by :meth:`async_compile`.

        Returns:
            :class:`JobResult` with current ``status``.
            When ``status == "completed"``, call :meth:`get_job_pdf` to
            download the PDF (it is deleted from the server after download).

        Raises:
            :class:`~FormaTex.FormaTexError`: Job not found (expired or never existed).
        """
        data = self._http.get_json(f"/api/v1/jobs/{job_id}")
        result = data.get("result") or {}
        return JobResult(
            job_id=data.get("id", job_id),
            status=data.get("status", "unknown"),
            log=result.get("log", ""),
            duration_ms=result.get("duration", 0),
            error=result.get("error", ""),
            success=result.get("success", False),
        )

    def get_job_pdf(self, job_id: str) -> bytes:
        """Download the PDF for a completed async job.

        The PDF is **deleted from the server immediately after this call**
        (one-time download). Save the bytes before calling again.

        Args:
            job_id: ID of a job with ``status == "completed"``.

        Returns:
            Raw PDF bytes.
        """
        return self._http.get_bytes(f"/api/v1/jobs/{job_id}/pdf")

    def get_job_log(self, job_id: str) -> str:
        """Fetch the compiler log for an async job (available after completion).

        Args:
            job_id: Job ID.

        Returns:
            Compiler log as plain text.
        """
        data = self._http.get_json(f"/api/v1/jobs/{job_id}/log")
        return data.get("log", "")

    def delete_job(self, job_id: str) -> None:
        """Delete a job and its associated files from the server.

        Useful to free storage early; jobs are auto-deleted after download
        or after a TTL window regardless.

        Args:
            job_id: Job ID to delete.
        """
        self._http.delete_json(f"/api/v1/jobs/{job_id}")

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> CompileResult:
        """Block until an async job completes and return the result.

        Polls :meth:`get_job` every ``poll_interval`` seconds. Downloads the PDF
        automatically when the job reaches ``completed``.

        Args:
            job_id: ID returned by :meth:`async_compile`.
            poll_interval: Seconds between status checks (default 2).
            timeout: Maximum total wait time in seconds (default 300).

        Returns:
            :class:`CompileResult` with the compiled PDF bytes.

        Raises:
            :class:`~FormaTex.CompilationError`: If the job failed.
            :class:`~FormaTex.FormaTexError`: If the timeout is exceeded.
        """
        from formatex.exceptions import CompilationError

        deadline = time.monotonic() + timeout

        while True:
            job = self.get_job(job_id)

            if job.status == "completed":
                pdf = self.get_job_pdf(job_id)
                return CompileResult(
                    pdf=pdf,
                    engine="",
                    duration_ms=job.duration_ms,
                    size_bytes=len(pdf),
                    job_id=job_id,
                    log=job.log,
                )

            if job.status == "failed":
                raise CompilationError(
                    job.error or "compilation failed",
                    log=job.log,
                    status_code=422,
                    body={"log": job.log, "error": job.error},
                )

            if time.monotonic() >= deadline:
                raise FormaTexError(
                    f"job {job_id} did not complete within {timeout}s (status: {job.status})",
                    status_code=None,
                )

            time.sleep(poll_interval)

    # ── Syntax Check ─────────────────────────────────────────────────────────

    def check_syntax(self, latex: str) -> SyntaxResult:
        """Validate LaTeX syntax without compiling (free, no quota cost).

        Uses a fast parser pass — does not invoke TeX.

        Args:
            latex: LaTeX source code.

        Returns:
            :class:`SyntaxResult` with ``valid`` flag and ``errors``/``warnings`` lists.
        """
        data = self._http.post_json("/api/v1/compile/check", {"latex": latex})
        return SyntaxResult(
            valid=data.get("valid", False),
            errors=data.get("errors", []),
            warnings=data.get("warnings", []),
        )

    # ── Lint ─────────────────────────────────────────────────────────────────

    def lint(self, latex: str) -> LintResult:
        """Run ChkTeX static analysis on LaTeX source.

        Returns structured diagnostics with line numbers, severity levels,
        and ChkTeX error codes. Useful for editor integrations and CI pipelines.

        Does **not** count against your monthly compilation quota.

        Args:
            latex: LaTeX source code.

        Returns:
            :class:`LintResult` with per-diagnostic details and aggregate counts.

        Example::

            result = client.lint(latex)
            for d in result.diagnostics:
                print(f"  Line {d.line}: [{d.severity}] {d.message}")
            if not result.valid:
                print(f"{result.error_count} error(s) found")
        """
        data = self._http.post_json("/api/v1/lint", {"latex": latex})
        diagnostics = [
            LintDiagnostic(
                line=d.get("line", 0),
                column=d.get("column", 0),
                severity=d.get("severity", "warning"),
                message=d.get("message", ""),
                source=d.get("source", "chktex"),
                code=d.get("code", ""),
            )
            for d in (data.get("diagnostics") or [])
        ]
        return LintResult(
            diagnostics=diagnostics,
            duration_ms=data.get("duration", 0),
        )

    # ── Convert ──────────────────────────────────────────────────────────────

    def convert(
        self,
        latex: str,
        *,
        files: list[dict] | None = None,
    ) -> ConvertResult:
        """Convert LaTeX source to a Word document (DOCX) via pandoc.

        Math is converted to native OOXML equations (Word's equation editor).
        Section structure, tables, and images are preserved.

        Counts against your monthly compilation quota (engine logged as ``pandoc``).

        Args:
            latex: LaTeX source code.
            files: Companion files (images, .bib) — use :func:`file_entry`.

        Returns:
            :class:`ConvertResult` with raw ``.docx`` bytes.

        Example::

            result = client.convert(latex)
            Path("document.docx").write_bytes(result.docx)
        """
        body: dict[str, Any] = {"latex": latex}
        if files:
            body["files"] = files
        docx = self._http.post_bytes("/api/v1/convert", body)
        return ConvertResult(docx=docx, size_bytes=len(docx))

    def convert_to_file(
        self,
        latex: str,
        output_path: str | Path,
        *,
        files: list[dict] | None = None,
    ) -> ConvertResult:
        """Convert LaTeX to DOCX and write directly to a file.

        Args:
            latex: LaTeX source code.
            output_path: Destination path for the ``.docx`` file.
            files: Companion files — use :func:`file_entry`.

        Returns:
            :class:`ConvertResult`.
        """
        result = self.convert(latex, files=files)
        Path(output_path).write_bytes(result.docx)
        return result

    # ── Usage ────────────────────────────────────────────────────────────────

    def get_usage(self) -> UsageStats:
        """Get current month's compilation usage for this API key.

        Returns:
            :class:`UsageStats` with plan info and compilation counts.
        """
        data = self._http.get_json("/api/v1/usage")
        comp = data.get("compilations", {})
        period = data.get("period", {})
        return UsageStats(
            plan=data.get("plan", ""),
            compilations_used=comp.get("used", data.get("compilationsUsed", 0)),
            compilations_limit=comp.get("limit", data.get("compilationsLimit", 0)),
            period_start=period.get("start", data.get("periodStart", "")),
            period_end=period.get("end", data.get("periodEnd", "")),
            overage=comp.get("overage", data.get("overage", 0)),
            raw=data,
        )

    # ── Engines ──────────────────────────────────────────────────────────────

    def list_engines(self) -> list[dict]:
        """List available compilation engines and their status.

        Returns:
            List of engine info dicts (name, available, version, etc.).
        """
        data = self._http.get_json("/api/v1/engines")
        return data.get("engines", [])

    # ── Compilation PDF ───────────────────────────────────────────────────────

    def get_compilation_pdf(self, compilation_id: str) -> bytes:
        """Download the PDF for a stored synchronous compilation by its ID.

        Sync compilations with ``jobId`` in the response can be retrieved here.

        Args:
            compilation_id: The ``jobId`` from a :class:`CompileResult`.

        Returns:
            Raw PDF bytes.
        """
        return self._http.get_bytes(f"/api/v1/compilations/{compilation_id}/pdf")

    # ── Equation Rendering ────────────────────────────────────────────────────

    def render_equation(
        self,
        latex: str,
        *,
        format: str = "png",
        dpi: int | None = None,
        display: bool = False,
        transparent: bool = False,
        padding: int | None = None,
        packages: list[str] | None = None,
    ) -> RenderResult:
        """Render a LaTeX math string to a PNG or SVG image.

        Does **not** count against your monthly compilation quota.
        Rate limit: 60 requests/minute per API key.

        Args:
            latex: Math content only — no delimiters (e.g. ``E = mc^2``).
            format: ``"png"`` (default) or ``"svg"``.
            dpi: PNG resolution, 72–600. Ignored for SVG.
            display: ``True`` for display (centred) math, ``False`` for inline.
            transparent: ``True`` for transparent background.
            padding: Border around the equation in pt (0–20).
            packages: Extra packages to load (up to 5). Allowed values:
                ``mhchem``, ``siunitx``, ``xcolor``, ``physics``, ``bm``,
                ``mathtools``, ``esint``, ``cancel``, ``chemfig``, ``tikz``.

        Returns:
            :class:`RenderResult` with raw image bytes and pixel dimensions.

        Example::

            result = client.render_equation(r"E = mc^2", format="svg")
            Path("equation.svg").write_bytes(result.data)
        """
        body: dict[str, Any] = {"latex": latex, "format": format, "display": display, "transparent": transparent}
        if dpi is not None:
            body["dpi"] = dpi
        if padding is not None:
            body["padding"] = padding
        if packages:
            body["packages"] = packages

        data = self._http.post_json("/api/v1/render/equation", body)
        return RenderResult(
            data=base64.b64decode(data["image"]),
            format=data.get("format", format),
            width=data.get("width", 0),
            height=data.get("height", 0),
        )

    def render_equations(self, equations: list[dict]) -> list[RenderResult]:
        """Render up to 20 equations in a single parallel request.

        Each item in ``equations`` accepts the same keys as
        :meth:`render_equation` (``latex``, ``format``, ``dpi``, ``display``,
        ``transparent``, ``padding``, ``packages``).

        Partial failures do not fail the whole batch — failed items have a
        non-empty ``error`` field and empty ``data``.

        Args:
            equations: List of equation dicts (max 20).

        Returns:
            Ordered list of :class:`RenderResult`, one per input equation.

        Example::

            results = client.render_equations([
                {"latex": r"E = mc^2", "format": "png"},
                {"latex": r"a^2 + b^2 = c^2", "format": "svg", "display": True},
            ])
            for r in results:
                if r.error:
                    print("failed:", r.error)
                else:
                    print(f"rendered {r.format} {r.width}x{r.height}")
        """
        data = self._http.post_json("/api/v1/render/equations", {"equations": equations})
        results: list[RenderResult] = []
        for item in data.get("results", []):
            if "error" in item:
                results.append(RenderResult(data=b"", format=item.get("format", ""), width=0, height=0, error=item["error"]))
            else:
                results.append(RenderResult(
                    data=base64.b64decode(item["image"]),
                    format=item.get("format", ""),
                    width=item.get("width", 0),
                    height=item.get("height", 0),
                ))
        return results

    # ── Projects ──────────────────────────────────────────────────────────────

    def _parse_project(self, raw: dict) -> Project:
        return Project(
            id=raw.get("id", ""),
            name=raw.get("name", ""),
            main_file=raw.get("mainFile", ""),
            file_count=raw.get("fileCount", 0),
            created_at=raw.get("createdAt", ""),
            updated_at=raw.get("updatedAt", ""),
            raw=raw,
        )

    def list_projects(self) -> list[Project]:
        """List all projects belonging to this API key's user.

        Returns:
            List of :class:`Project` objects.
        """
        data = self._http.get_json("/api/v1/projects")
        return [self._parse_project(p) for p in data.get("projects", [])]

    def get_project(self, project_id: str) -> Project:
        """Get a single project by ID.

        Args:
            project_id: Project UUID.

        Returns:
            :class:`Project`.
        """
        data = self._http.get_json(f"/api/v1/projects/{project_id}")
        return self._parse_project(data)

    def list_project_files(self, project_id: str) -> list[ProjectFile]:
        """List file metadata for all files in a project.

        Args:
            project_id: Project UUID.

        Returns:
            List of :class:`ProjectFile` with path, size, and mime type.
        """
        data = self._http.get_json(f"/api/v1/projects/{project_id}/files")
        return [
            ProjectFile(
                path=f.get("path", ""),
                size=f.get("size", 0),
                mime_type=f.get("mimeType", ""),
                updated_at=f.get("updatedAt", ""),
                raw=f,
            )
            for f in data.get("files", [])
        ]

    def read_project_file(self, project_id: str, file_name: str) -> bytes:
        """Download the raw content of a project file.

        Args:
            project_id: Project UUID.
            file_name: File path within the project (e.g. ``"main.tex"``).

        Returns:
            Raw file bytes.
        """
        return self._http.get_bytes(f"/api/v1/projects/{project_id}/files/{file_name.lstrip('/')}")

    def upsert_project_file(
        self,
        project_id: str,
        file_name: str,
        content: bytes,
        *,
        content_type: str = "text/plain",
    ) -> None:
        """Create or overwrite a file in a project.

        Args:
            project_id: Project UUID.
            file_name: File path within the project (e.g. ``"main.tex"``).
            content: Raw file bytes.
            content_type: MIME type (default ``text/plain``). Use
                ``application/octet-stream`` for binary assets.
        """
        self._http.put_raw(
            f"/api/v1/projects/{project_id}/files/{file_name.lstrip('/')}",
            content,
            content_type,
        )

    def delete_project_file(self, project_id: str, file_name: str) -> None:
        """Delete a file from a project.

        Args:
            project_id: Project UUID.
            file_name: File path within the project.
        """
        self._http.delete_json(f"/api/v1/projects/{project_id}/files/{file_name.lstrip('/')}")

    def rename_project_file(self, project_id: str, old_path: str, new_path: str) -> None:
        """Rename (move) a file within a project.

        Args:
            project_id: Project UUID.
            old_path: Current file path.
            new_path: New file path.
        """
        self._http.post_empty(
            f"/api/v1/projects/{project_id}/files/rename",
            {"oldPath": old_path, "newPath": new_path},
        )

    def export_project(self, project_id: str) -> bytes:
        """Export an entire project as a ZIP archive.

        Args:
            project_id: Project UUID.

        Returns:
            Raw ZIP bytes containing all project files.
        """
        return self._http.get_bytes(f"/api/v1/projects/{project_id}/export")

    # ── Document Intelligence ─────────────────────────────────────────────────

    def word_count(self, latex: str) -> WordCountResult:
        """Count words, headers, floats, and math in a LaTeX document.

        Uses texcount under the hood — no compilation, no quota cost.

        Args:
            latex: Full LaTeX source.

        Returns:
            :class:`WordCountResult` with text, header, caption, and total word
            counts plus structure counts (headers, floats, inline and display math).
        """
        data = self._http.post_json("/api/v1/analyze/wordcount", {"latex": latex})
        return WordCountResult(
            text_words=data.get("textWords", 0),
            header_words=data.get("headerWords", 0),
            caption_words=data.get("captionWords", 0),
            headers=data.get("headers", 0),
            floats=data.get("floats", 0),
            math_inline=data.get("mathInline", 0),
            math_display=data.get("mathDisplay", 0),
            total_words=data.get("totalWords", 0),
            duration_ms=data.get("durationMs", 0),
        )

    def extract_dependencies(self, latex: str) -> DependenciesResult:
        """Extract all \\usepackage declarations and check their availability.

        No compilation needed — pure static analysis.

        Args:
            latex: Full LaTeX source.

        Returns:
            :class:`DependenciesResult` with all declared packages split into
            ``available`` (found in TeX Live) and ``unavailable`` lists.
        """
        data = self._http.post_json("/api/v1/analyze/dependencies", {"latex": latex})
        return DependenciesResult(
            packages=data.get("packages") or [],
            available=data.get("available") or [],
            unavailable=data.get("unavailable") or [],
            duration_ms=data.get("durationMs", 0),
        )

    def check_packages(self, names: list[str]) -> list[PackageStatus]:
        """Check whether TeX packages are installed in TeX Live.

        Args:
            names: Package names without ``.sty`` suffix, e.g.
                   ``["pgfplots", "tikz", "mhchem"]``. Maximum 50 per call.

        Returns:
            List of :class:`PackageStatus` objects in the same order as *names*.
        """
        joined = ",".join(names)
        data = self._http.get_json(f"/api/v1/analyze/packages?names={joined}")
        return [
            PackageStatus(name=p["name"], available=p["available"])
            for p in data.get("packages", [])
        ]

    def extract_metadata(self, latex: str) -> DocumentMetadata:
        """Extract structured metadata from a LaTeX document.

        Parses ``\\title``, ``\\author``, ``\\date``, ``abstract`` environment,
        and ``\\keywords`` — no compilation, no quota cost.

        Note:
            Results are best-effort. Documents using custom macros or
            non-standard document classes may yield partial results.

        Args:
            latex: Full LaTeX source.

        Returns:
            :class:`DocumentMetadata` with title, authors, date, abstract,
            and keywords.
        """
        data = self._http.post_json("/api/v1/analyze/metadata", {"latex": latex})
        return DocumentMetadata(
            title=data.get("title", ""),
            authors=data.get("authors") or [],
            date=data.get("date", ""),
            abstract=data.get("abstract", ""),
            keywords=data.get("keywords") or [],
        )

    def analyze_bibliography(self, bib: str) -> BibResult:
        """Parse a BibTeX string into structured entries with formatted citations.

        Handles ``@article``, ``@book``, ``@inproceedings``, ``@phdthesis``,
        ``@incollection``, and all other entry types (generic fallback).
        Supports ``@string`` macros and ``#`` concatenation.
        No compilation, no quota cost.

        Args:
            bib: Raw BibTeX string (one or more entries).

        Returns:
            :class:`BibResult` with parsed entries and APA/MLA/Chicago citations.
        """
        data = self._http.post_json("/api/v1/analyze/bibliography", {"bib": bib})

        entries = []
        for e in data.get("entries") or []:
            fmt = e.get("formatted") or {}
            entries.append(BibEntry(
                key=e.get("key", ""),
                type=e.get("type", ""),
                fields=e.get("fields") or {},
                authors=e.get("authors") or [],
                formatted=BibFormatted(
                    apa=fmt.get("apa", ""),
                    mla=fmt.get("mla", ""),
                    chicago=fmt.get("chicago", ""),
                ),
            ))

        return BibResult(
            entries=entries,
            count=data.get("count", len(entries)),
            duration_ms=data.get("durationMs", 0),
        )
