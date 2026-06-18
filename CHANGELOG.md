# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.2.0] - 2026-06-18

### Added
- `word_count(latex)` — word, header, caption, float, and math counts via texcount (no quota)
- `extract_dependencies(latex)` — list all `\usepackage` declarations; split into available/unavailable
- `check_packages(names)` — check whether TeX packages are installed in TeX Live
- `extract_metadata(latex)` — extract title, authors, date, abstract, and keywords
- New dataclasses: `WordCountResult`, `DependenciesResult`, `PackageStatus`, `DocumentMetadata`

---

## [1.1.0] - 2026-06-17

### Added
- `render_equation(latex, **kwargs)` — render a single math equation as PNG or SVG
- `render_equations(equations)` — batch render up to 20 equations
- `get_compilation_pdf(compilation_id)` — retrieve stored PDF from a sync compile by job ID
- `list_projects()` — list all projects accessible via API key
- `get_project(project_id)` — get a single project
- `list_project_files(project_id)` — list files in a project
- `read_project_file(project_id, file_name)` — download a project file as raw bytes
- `upsert_project_file(project_id, file_name, content, content_type)` — create or replace a project file
- `delete_project_file(project_id, file_name)` — delete a project file
- `rename_project_file(project_id, old_path, new_path)` — rename/move a project file
- `export_project(project_id)` — download the full project as a ZIP archive
- New dataclasses: `RenderResult`, `Project`, `ProjectFile`
- `overage` field added to `UsageStats`
- `put_raw` and `post_empty` internal HTTP methods for binary uploads and no-body responses

---

## [1.0.4] - 2026-02-28

### Removed
- `base_url` and `staging` constructor parameters removed from public API

---

## [1.0.3] - 2026-02-20

### Fixed
- Package renamed to lowercase `formatex` throughout for PEP 8 compliance

---

## [1.0.0] - 2026-02-18

### Added
- Initial release
- `FormaTexClient` with full API coverage: `compile`, `compile_smart`, `compile_to_file`, `async_compile`, `wait_for_job`, `get_job`, `get_job_pdf`, `get_job_log`, `delete_job`, `check_syntax`, `lint`, `convert`, `convert_to_file`, `get_usage`, `list_engines`
- `file_entry()` helper for attaching companion files
- Typed exceptions: `FormaTexError`, `AuthenticationError`, `CompilationError`, `RateLimitError`, `PlanLimitError`
- Sync and async context manager support
- Python ≥ 3.9, only dependency: `httpx`
