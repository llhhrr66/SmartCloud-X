import hashlib
import io
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from uuid import uuid4

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

try:
    from minio import Minio
except ImportError:  # pragma: no cover - exercised in integration environments
    Minio = None

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".text"}
OBJECT_STORAGE_SOURCE_TYPES = {"minio", "object_storage"}


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
        self._require_supported_text_extension(path.name, label="import file")
        try:
            content = self._validate_loaded_content(path.read_text(encoding="utf-8"), file_id)
        except UnicodeDecodeError as exc:
            raise ValueError(f"Import file is not valid UTF-8 text: {file_id}") from exc
        return path, content

    def load_admin_document_source(
        self,
        file_id: str,
        *,
        source_type: str,
        source_uri: str | None = None,
    ) -> tuple[str, str, str]:
        normalized_source_type = source_type.strip().lower()
        if normalized_source_type in OBJECT_STORAGE_SOURCE_TYPES:
            bucket, object_key = self._resolve_minio_object(file_id, source_uri)
            content = self._load_minio_object_text(bucket, object_key)
            return (
                f"{bucket}/{object_key}",
                source_uri.strip() if source_uri and source_uri.strip() else f"minio://{bucket}/{object_key}",
                content,
            )

        path, content = self.load_import_file(file_id)
        return (
            self.display_path(path),
            source_uri.strip() if source_uri and source_uri.strip() else path.as_uri(),
            content,
        )

    def begin_admin_upload(self, filename: str, content_type: str | None = None) -> tuple[str, str, str, str, str]:
        normalized_name = Path(filename.strip()).name.strip()
        if not normalized_name:
            raise ValueError("filename must not be empty")
        self._require_supported_text_extension(normalized_name, label="upload filename")
        bucket = self.settings.minio_bucket or ""
        if not bucket:
            raise ValueError("SMARTCLOUD_MINIO_BUCKET is required for object-storage uploads")
        upload_id = f"upl-{uuid4().hex[:12]}"
        suffix = Path(normalized_name).suffix.lower()
        stem = self._sanitize_filename_component(Path(normalized_name).stem)
        date_prefix = datetime.now(UTC).strftime("%Y/%m/%d")
        object_key = f"admin-uploads/{date_prefix}/{upload_id}/{stem}{suffix}"
        source_uri = f"minio://{bucket}/{object_key}"
        resolved_file_id = f"{bucket}/{object_key}"
        return upload_id, bucket, object_key, source_uri, resolved_file_id

    def upload_admin_file_bytes(
        self,
        *,
        file_id: str,
        source_uri: str,
        content: bytes,
        content_type: str | None = None,
    ) -> dict[str, str | int | None]:
        if not content:
            raise ValueError("upload body must not be empty")
        bucket, object_key = self._resolve_minio_object(file_id, source_uri)
        self._require_supported_text_extension(object_key, label="object-storage file")
        client = self._minio_client()
        try:
            if not client.bucket_exists(bucket):
                raise ValueError(
                    f"Object storage bucket is unavailable or does not exist: {bucket}"
                )
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - backend issues should surface as validation-style errors
            raise ValueError(
                f"Object storage bucket is unavailable or does not exist: {bucket}"
            ) from exc
        normalized_content_type = (content_type or "text/markdown; charset=utf-8").strip()
        client.put_object(
            bucket_name=bucket,
            object_name=object_key,
            data=io.BytesIO(content),
            length=len(content),
            content_type=normalized_content_type,
        )
        checksum = hashlib.sha256(content).hexdigest()[:16]
        return {
            "bucket": bucket,
            "object_key": object_key,
            "file_id": object_key,
            "resolved_file_id": f"{bucket}/{object_key}",
            "source_uri": f"minio://{bucket}/{object_key}",
            "content_type": normalized_content_type,
            "size_bytes": len(content),
            "checksum": checksum,
        }

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

    def _load_minio_object_text(self, bucket: str, object_key: str) -> str:
        self._require_supported_text_extension(object_key, label="object-storage file")
        client = self._minio_client()
        response = None
        try:
            response = client.get_object(bucket_name=bucket, object_name=object_key)
            try:
                return self._validate_loaded_content(response.read().decode("utf-8"), f"{bucket}/{object_key}")
            except UnicodeDecodeError as exc:
                raise ValueError(f"Object storage file is not valid UTF-8 text: {bucket}/{object_key}") from exc
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - service should convert backend issues to validation-style errors
            raise ValueError(f"Object storage file could not be read: {bucket}/{object_key}") from exc
        finally:
            if response is not None:
                response.close()

    def _resolve_minio_object(self, file_id: str, source_uri: str | None) -> tuple[str, str]:
        object_key = file_id.strip().lstrip("/")
        if not object_key:
            raise ValueError("file_id must not be empty")
        bucket = self.settings.minio_bucket or ""

        normalized_source_uri = source_uri.strip() if source_uri and source_uri.strip() else None
        if normalized_source_uri:
            parsed = urlparse(normalized_source_uri)
            if parsed.scheme == "minio":
                if parsed.netloc.strip():
                    bucket = parsed.netloc.strip()
                if parsed.path.strip("/"):
                    object_key = parsed.path.lstrip("/")
            elif parsed.scheme in {"http", "https"} and self.settings.minio_endpoint:
                endpoint = urlparse(self._normalized_endpoint(self.settings.minio_endpoint))
                if parsed.netloc == endpoint.netloc and parsed.path.strip("/"):
                    parts = parsed.path.lstrip("/").split("/", 1)
                    bucket = parts[0]
                    if len(parts) > 1 and parts[1].strip():
                        object_key = parts[1].strip()

        if not bucket:
            raise ValueError("SMARTCLOUD_MINIO_BUCKET is required for object-storage document reads")
        if not object_key:
            raise ValueError("object-storage file key must not be empty")
        return bucket, object_key

    def _minio_client(self):
        if Minio is None:
            raise ValueError("MinIO client dependency is unavailable")
        if not self.settings.minio_endpoint:
            raise ValueError("SMARTCLOUD_MINIO_ENDPOINT is required for object-storage document reads")
        if not self.settings.minio_access_key or not self.settings.minio_secret_key:
            raise ValueError(
                "SMARTCLOUD_MINIO_ACCESS_KEY and SMARTCLOUD_MINIO_SECRET_KEY are required for object-storage document reads"
            )
        parsed = urlparse(self._normalized_endpoint(self.settings.minio_endpoint))
        return Minio(
            parsed.netloc,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=parsed.scheme == "https",
        )

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
            return PurePosixPath(path.resolve().relative_to(root)).as_posix()
        except ValueError:
            return PurePosixPath(path.resolve()).as_posix()

    @staticmethod
    def _normalized_endpoint(endpoint: str) -> str:
        parsed = urlparse(endpoint)
        if parsed.scheme and parsed.netloc:
            return endpoint.rstrip("/")
        return f"http://{endpoint.strip().rstrip('/')}"

    @staticmethod
    def _validate_loaded_content(content: str, file_id: str) -> str:
        normalized = content.strip()
        if len(normalized) < 20:
            raise ValueError(f"Import file content shorter than minimum ingestion size: {file_id}")
        return normalized

    @staticmethod
    def _require_supported_text_extension(value: str, *, label: str) -> None:
        suffix = Path(value).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported {label} extension: {suffix or '(none)'}")

    @staticmethod
    def _sanitize_filename_component(value: str) -> str:
        normalized = "".join(character.lower() if character.isalnum() else "-" for character in value.strip())
        collapsed = "-".join(part for part in normalized.split("-") if part)
        return collapsed or "upload"

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
