from functools import lru_cache
from pathlib import Path, PurePosixPath

from app.core.config import get_settings
from app.core.metrics import (
    FILE_IMPORT_FAILURES_TOTAL,
    FILE_IMPORT_FILES_TOTAL,
    FILE_IMPORT_RUNS_TOTAL,
)
from app.core.tracing import start_span
from app.models.knowledge import (
    FileImportPreviewItem,
    FileImportPreviewRequest,
    FileImportPreviewResponse,
    FileImportRequest,
    FileImportResponse,
    FileImportResultItem,
    IngestDocumentRequest,
    SourceSeed,
)
from app.services.ingestion import IngestionService, get_ingestion_service

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".text"}


class FileImportService:
    def __init__(self, ingestion_service: IngestionService) -> None:
        self.ingestion_service = ingestion_service
        self.settings = get_settings()

    def preview(self, request: FileImportPreviewRequest) -> FileImportPreviewResponse:
        with start_span(
            "knowledge.file_import.preview",
            smartcloud_import_directory=request.directory or ".",
            smartcloud_import_glob=request.glob_pattern,
            smartcloud_import_max_files=request.max_files,
        ) as span:
            directory = self._resolve_directory(request.directory)
            files = self._collect_files(directory, request.glob_pattern, request.max_files)
            items = [self._build_preview_item(path) for path in files]
            if span is not None:
                span.set_attribute("smartcloud.import.matched_files", len(items))
                span.set_attribute(
                    "smartcloud.import.importable_files",
                    sum(1 for item in items if item.importable),
                )
            return FileImportPreviewResponse(
                importRoot=str(self.settings.import_root),
                directory=request.directory or ".",
                glob=request.glob_pattern,
                matchedFiles=len(items),
                importableFiles=sum(1 for item in items if item.importable),
                items=items,
            )

    def import_files(self, request: FileImportRequest) -> FileImportResponse:
        with start_span(
            "knowledge.file_import.run",
            smartcloud_import_directory=request.directory or ".",
            smartcloud_import_glob=request.glob_pattern,
            smartcloud_import_requested_max_files=request.max_files,
        ) as span:
            FILE_IMPORT_RUNS_TOTAL.inc()
            effective_max_files = min(request.max_files, self.settings.max_import_files)
            preview = self.preview(
                FileImportPreviewRequest(
                    directory=request.directory,
                    glob=request.glob_pattern,
                    maxFiles=effective_max_files,
                )
            )
            import_root = self.settings.import_root.expanduser().resolve()
            importable_paths = [
                (import_root / item.path).resolve()
                if not Path(item.path).is_absolute()
                else Path(item.path)
                for item in preview.items
                if item.importable
            ]
            if not importable_paths:
                raise ValueError(
                    "No importable markdown/text files were found for the requested directory."
                )

            source_seed = request.source or self._derive_source_seed(request.directory)
            source = self.ingestion_service.resolve_source(request.source_id, source_seed)

            results: list[FileImportResultItem] = []
            for path in importable_paths:
                FILE_IMPORT_FILES_TOTAL.inc()
                title = self._title_from_path(path)
                try:
                    content = path.read_text(encoding="utf-8").strip()
                    if len(content) < 20:
                        raise ValueError("content shorter than minimum ingestion size")
                    title = self._extract_title(content, path)
                    response = self.ingestion_service.ingest_document(
                        IngestDocumentRequest(
                            sourceId=source.id,
                            title=title,
                            content=content,
                            tags=request.tags,
                            language=request.language,
                            sourceType="filesystem",
                            sourceUri=path.as_uri(),
                        )
                    )
                    source = response.source
                    warning = ", ".join(response.job.warnings) if response.job.warnings else None
                    results.append(
                        FileImportResultItem(
                            path=self._display_path(path),
                            title=title,
                            status="reused" if response.chunks_created == 0 else "imported",
                            documentId=response.document.id,
                            chunksCreated=response.chunks_created,
                            warning=warning,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - import summary should capture per-file failures
                    FILE_IMPORT_FAILURES_TOTAL.inc()
                    results.append(
                        FileImportResultItem(
                            path=self._display_path(path),
                            title=title,
                            status="failed",
                            error=str(exc),
                        )
                    )

            imported_files = sum(1 for item in results if item.status == "imported")
            reused_files = sum(1 for item in results if item.status == "reused")
            failed_files = sum(1 for item in results if item.status == "failed")
            if span is not None:
                span.set_attribute("smartcloud.import.processed_files", len(results))
                span.set_attribute("smartcloud.import.imported_files", imported_files)
                span.set_attribute("smartcloud.import.reused_files", reused_files)
                span.set_attribute("smartcloud.import.failed_files", failed_files)

            return FileImportResponse(
                importRoot=str(self.settings.import_root),
                directory=request.directory or ".",
                glob=request.glob_pattern,
                source=source,
                processedFiles=len(results),
                importedFiles=imported_files,
                reusedFiles=reused_files,
                failedFiles=failed_files,
                results=results,
            )

    def load_import_file(self, file_id: str) -> tuple[Path, str]:
        path = self.resolve_file_id(file_id)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported import file extension: {path.suffix or '(none)'}")
        try:
            content = path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ValueError(f"Import file is not valid UTF-8 text: {file_id}") from exc
        if len(content) < 20:
            raise ValueError(f"Import file content shorter than minimum ingestion size: {file_id}")
        return path, content

    def resolve_file_id(self, file_id: str) -> Path:
        if not file_id.strip():
            raise ValueError("file_id must not be empty")
        root = self.settings.import_root.expanduser().resolve()
        candidate = Path(file_id.strip()).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        self._ensure_within_root(candidate, root, message=f"Import file is outside the configured import root: {file_id}")
        if not candidate.exists() or not candidate.is_file():
            raise ValueError(f"Import file does not exist: {file_id}")
        return candidate

    def display_path(self, path: Path) -> str:
        return self._display_path(path)

    def _resolve_directory(self, directory: str | None) -> Path:
        root = self.settings.import_root.expanduser().resolve()
        candidate = root if not directory or directory == "." else Path(directory).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        self._ensure_within_root(
            candidate,
            root,
            message=f"Import directory is outside the configured import root: {candidate}",
        )
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"Import directory does not exist: {candidate}")
        return candidate

    def _collect_files(self, directory: Path, glob_pattern: str, max_files: int) -> list[Path]:
        root = self.settings.import_root.expanduser().resolve()
        pattern = self._normalize_glob_pattern(glob_pattern)
        files = sorted(
            path
            for path in directory.glob(pattern)
            if path.is_file() and self._is_within_root(path.resolve(), root)
        )
        return files[:max_files]

    def _build_preview_item(self, path: Path) -> FileImportPreviewItem:
        note = None
        importable = True
        content: str | None = None
        extension = path.suffix.lower() or "(none)"
        if extension not in SUPPORTED_EXTENSIONS:
            importable = False
            note = "unsupported file extension"
        else:
            try:
                content = path.read_text(encoding="utf-8").strip()
            except UnicodeDecodeError:
                importable = False
                note = "file is not valid UTF-8 text"
            if importable and len(content) < 20:
                importable = False
                note = "content shorter than minimum ingestion size"
        return FileImportPreviewItem(
            path=self._display_path(path),
            title=self._extract_title(content, path),
            extension=extension,
            sizeBytes=path.stat().st_size,
            importable=importable,
            note=note,
        )

    def _derive_source_seed(self, directory: str | None) -> SourceSeed:
        label = (directory or "filesystem-import").strip("/ ") or "filesystem-import"
        name = label.split("/")[-1].replace("-", " ").replace("_", " ").strip() or "Filesystem Import"
        display_name = " ".join(part.capitalize() for part in name.split()) or "Filesystem Import"
        uri = str(self._resolve_directory(directory).as_uri())
        return SourceSeed(
            name=display_name,
            kind="manual",
            uri=uri,
            description=f"Filesystem batch import from {label}",
            tags=["filesystem", "batch-import"],
        )

    def _display_path(self, path: Path) -> str:
        root = self.settings.import_root.expanduser().resolve()
        try:
            return str(path.resolve().relative_to(root))
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _ensure_within_root(path: Path, root: Path, *, message: str) -> None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(message) from exc

    @staticmethod
    def _is_within_root(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _normalize_glob_pattern(glob_pattern: str) -> str:
        pattern = glob_pattern.strip() or "**/*"
        normalized_pattern = pattern.replace("\\", "/")
        parts = PurePosixPath(normalized_pattern).parts
        if (
            normalized_pattern.startswith("/")
            or (parts and parts[0].endswith(":"))
            or any(part == ".." for part in parts)
        ):
            raise ValueError("Import glob pattern is outside the configured import root")
        return normalized_pattern

    @staticmethod
    def _title_from_path(path: Path) -> str:
        return path.stem.replace("-", " ").replace("_", " ").strip() or path.name

    def _extract_title(self, content: str | None, path: Path) -> str:
        if content:
            for line in content.splitlines():
                candidate = line.strip()
                if not candidate:
                    continue
                if candidate.startswith("#"):
                    candidate = candidate.lstrip("#").strip()
                if candidate:
                    return candidate[:80]
        return self._title_from_path(path)


@lru_cache(maxsize=1)
def get_file_import_service() -> FileImportService:
    return FileImportService(get_ingestion_service())
