from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from app.models.admin import AdminAsyncJob, KnowledgeBaseProfile, KnowledgeDocumentProfile
from app.models.knowledge import IngestionJob, KnowledgeChunk, KnowledgeDocument, KnowledgeSource

try:
    import pymysql
except ImportError:  # pragma: no cover - exercised in integration environments
    pymysql = None


@dataclass(frozen=True)
class KnowledgeMetadataState:
    knowledge_base_profiles: list[KnowledgeBaseProfile]
    document_profiles: list[KnowledgeDocumentProfile]
    admin_jobs: list[AdminAsyncJob]


@dataclass(frozen=True)
class KnowledgeRuntimeState:
    sources: list[KnowledgeSource]
    documents: list[KnowledgeDocument]
    chunks: list[KnowledgeChunk]
    ingestions: list[IngestionJob]


class MySQLKnowledgeMetadataBackend:
    KB_TABLE = "knowledge_runtime_kb_profiles"
    DOCUMENT_TABLE = "knowledge_runtime_document_profiles"
    JOB_TABLE = "knowledge_runtime_admin_jobs"

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._connection_params = self._build_connection_params(dsn)

    @staticmethod
    def _build_connection_params(dsn: str) -> dict[str, object]:
        parsed = urlparse(dsn)
        if parsed.scheme not in {"mysql", "mysql+pymysql"}:
            raise ValueError(f"unsupported mysql dsn scheme: {parsed.scheme}")
        database = parsed.path.lstrip("/")
        if not database:
            raise ValueError("mysql dsn is missing a database name")
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "database": database,
            "autocommit": False,
            "charset": "utf8mb4",
        }

    def _connect(self):
        if pymysql is None:
            raise RuntimeError("PyMySQL dependency is unavailable")
        params = dict(self._connection_params)
        cursor_module = getattr(pymysql, "cursors", None)
        dict_cursor = getattr(cursor_module, "DictCursor", None)
        if dict_cursor is not None:
            params["cursorclass"] = dict_cursor
        return pymysql.connect(**params)

    def _ensure_schema(self, cursor) -> None:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.KB_TABLE}` (
              kb_id VARCHAR(64) PRIMARY KEY,
              code VARCHAR(255) NOT NULL,
              scene VARCHAR(64) NOT NULL,
              language VARCHAR(64) NOT NULL,
              retrieval_mode VARCHAR(128) NOT NULL,
              embedding_model VARCHAR(255) NOT NULL,
              status VARCHAR(64) NOT NULL,
              created_at VARCHAR(64) NOT NULL,
              updated_at VARCHAR(64) NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.DOCUMENT_TABLE}` (
              doc_id VARCHAR(64) PRIMARY KEY,
              kb_id VARCHAR(64) NOT NULL,
              status VARCHAR(64) NOT NULL,
              parse_status VARCHAR(64) NOT NULL,
              index_status VARCHAR(64) NOT NULL,
              version_no INT NOT NULL,
              file_id TEXT NULL,
              source_type VARCHAR(64) NOT NULL,
              source_uri LONGTEXT NULL,
              indexed_at VARCHAR(64) NULL,
              error_message LONGTEXT NULL,
              latest_job_id VARCHAR(64) NULL
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.JOB_TABLE}` (
              job_id VARCHAR(64) PRIMARY KEY,
              job_type VARCHAR(128) NOT NULL,
              status VARCHAR(64) NOT NULL,
              progress INT NOT NULL,
              created_at VARCHAR(64) NOT NULL,
              params_json LONGTEXT NULL,
              result_file_id TEXT NULL,
              error_code VARCHAR(128) NULL,
              error_message LONGTEXT NULL,
              finished_at VARCHAR(64) NULL
            )
            """
        )

    def sync_from_local(
        self,
        *,
        knowledge_base_profiles: list[KnowledgeBaseProfile],
        document_profiles: list[KnowledgeDocumentProfile],
        admin_jobs: list[AdminAsyncJob],
    ) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                for profile in knowledge_base_profiles:
                    self._upsert_knowledge_base_profile(cursor, profile)
                for profile in document_profiles:
                    self._upsert_document_profile(cursor, profile)
                for job in admin_jobs:
                    self._upsert_admin_job(cursor, job)
            connection.commit()
        finally:
            connection.close()

    def replace_profiles(
        self,
        *,
        knowledge_base_profiles: list[KnowledgeBaseProfile],
        document_profiles: list[KnowledgeDocumentProfile],
    ) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(f"DELETE FROM `{self.KB_TABLE}`")
                cursor.execute(f"DELETE FROM `{self.DOCUMENT_TABLE}`")
                for profile in knowledge_base_profiles:
                    self._upsert_knowledge_base_profile(cursor, profile)
                for profile in document_profiles:
                    self._upsert_document_profile(cursor, profile)
            connection.commit()
        finally:
            connection.close()

    def load_state(self) -> KnowledgeMetadataState:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT kb_id, code, scene, language, retrieval_mode, embedding_model, status, created_at, updated_at
                    FROM `{self.KB_TABLE}`
                    """
                )
                kb_rows = cursor.fetchall() or []
                cursor.execute(
                    f"""
                    SELECT doc_id, kb_id, status, parse_status, index_status, version_no, file_id, source_type,
                           source_uri, indexed_at, error_message, latest_job_id
                    FROM `{self.DOCUMENT_TABLE}`
                    """
                )
                document_rows = cursor.fetchall() or []
                cursor.execute(
                    f"""
                    SELECT job_id, job_type, status, progress, created_at, params_json,
                           result_file_id, error_code, error_message, finished_at
                    FROM `{self.JOB_TABLE}`
                    """
                )
                job_rows = cursor.fetchall() or []
        finally:
            connection.close()
        return KnowledgeMetadataState(
            knowledge_base_profiles=[
                self._build_knowledge_base_profile(row) for row in kb_rows
            ],
            document_profiles=[
                self._build_document_profile(row) for row in document_rows
            ],
            admin_jobs=[self._build_admin_job(row) for row in job_rows],
        )

    def list_knowledge_base_profiles(self) -> list[KnowledgeBaseProfile]:
        return self.load_state().knowledge_base_profiles

    def list_document_profiles(self) -> list[KnowledgeDocumentProfile]:
        return self.load_state().document_profiles

    def list_admin_jobs(self) -> list[AdminAsyncJob]:
        return self.load_state().admin_jobs

    def upsert_knowledge_base_profile(self, profile: KnowledgeBaseProfile) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                self._upsert_knowledge_base_profile(cursor, profile)
            connection.commit()
        finally:
            connection.close()

    def upsert_document_profile(self, profile: KnowledgeDocumentProfile) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                self._upsert_document_profile(cursor, profile)
            connection.commit()
        finally:
            connection.close()

    def upsert_admin_job(self, job: AdminAsyncJob) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                self._upsert_admin_job(cursor, job)
            connection.commit()
        finally:
            connection.close()

    def _upsert_knowledge_base_profile(self, cursor, profile: KnowledgeBaseProfile) -> None:
        cursor.execute(
            f"""
            INSERT INTO `{self.KB_TABLE}` (
              kb_id, code, scene, language, retrieval_mode, embedding_model, status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              code = VALUES(code),
              scene = VALUES(scene),
              language = VALUES(language),
              retrieval_mode = VALUES(retrieval_mode),
              embedding_model = VALUES(embedding_model),
              status = VALUES(status),
              created_at = VALUES(created_at),
              updated_at = VALUES(updated_at)
            """,
            (
                profile.kb_id,
                profile.code,
                profile.scene,
                profile.language,
                profile.retrieval_mode,
                profile.embedding_model,
                profile.status,
                profile.created_at,
                profile.updated_at,
            ),
        )

    @staticmethod
    def _build_knowledge_base_profile(row: dict[str, object]) -> KnowledgeBaseProfile:
        return KnowledgeBaseProfile(
            kb_id=str(row["kb_id"]),
            code=str(row["code"]),
            scene=str(row["scene"]),
            language=str(row["language"]),
            retrieval_mode=str(row["retrieval_mode"]),
            embedding_model=str(row["embedding_model"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _upsert_document_profile(self, cursor, profile: KnowledgeDocumentProfile) -> None:
        cursor.execute(
            f"""
            INSERT INTO `{self.DOCUMENT_TABLE}` (
              doc_id, kb_id, status, parse_status, index_status, version_no, file_id, source_type,
              source_uri, indexed_at, error_message, latest_job_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              kb_id = VALUES(kb_id),
              status = VALUES(status),
              parse_status = VALUES(parse_status),
              index_status = VALUES(index_status),
              version_no = VALUES(version_no),
              file_id = VALUES(file_id),
              source_type = VALUES(source_type),
              source_uri = VALUES(source_uri),
              indexed_at = VALUES(indexed_at),
              error_message = VALUES(error_message),
              latest_job_id = VALUES(latest_job_id)
            """,
            (
                profile.doc_id,
                profile.kb_id,
                profile.status,
                profile.parse_status,
                profile.index_status,
                profile.version_no,
                profile.file_id,
                profile.source_type,
                profile.source_uri,
                profile.indexed_at,
                profile.error_message,
                profile.latest_job_id,
            ),
        )

    @staticmethod
    def _build_document_profile(row: dict[str, object]) -> KnowledgeDocumentProfile:
        return KnowledgeDocumentProfile(
            doc_id=str(row["doc_id"]),
            kb_id=str(row["kb_id"]),
            status=str(row["status"]),
            parse_status=str(row["parse_status"]),
            index_status=str(row["index_status"]),
            version_no=int(row["version_no"]),
            file_id=row.get("file_id"),
            source_type=str(row["source_type"]),
            source_uri=row.get("source_uri"),
            indexed_at=row.get("indexed_at"),
            error_message=row.get("error_message"),
            latest_job_id=row.get("latest_job_id"),
        )

    def _upsert_admin_job(self, cursor, job: AdminAsyncJob) -> None:
        cursor.execute(
            f"""
            INSERT INTO `{self.JOB_TABLE}` (
              job_id, job_type, status, progress, created_at, params_json, result_file_id,
              error_code, error_message, finished_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              job_type = VALUES(job_type),
              status = VALUES(status),
              progress = VALUES(progress),
              created_at = VALUES(created_at),
              params_json = VALUES(params_json),
              result_file_id = VALUES(result_file_id),
              error_code = VALUES(error_code),
              error_message = VALUES(error_message),
              finished_at = VALUES(finished_at)
            """,
            (
                job.job_id,
                job.type,
                job.status,
                job.progress,
                job.created_at,
                json.dumps(job.params, ensure_ascii=False) if job.params is not None else None,
                job.result_file_id,
                job.error_code,
                job.error_message,
                job.finished_at,
            ),
        )

    @staticmethod
    def _build_admin_job(row: dict[str, object]) -> AdminAsyncJob:
        return AdminAsyncJob(
            job_id=str(row["job_id"]),
            type=str(row["job_type"]),
            status=str(row["status"]),
            progress=int(row["progress"]),
            created_at=str(row["created_at"]),
            params=json.loads(row["params_json"]) if row.get("params_json") else None,
            result_file_id=row.get("result_file_id"),
            error_code=row.get("error_code"),
            error_message=row.get("error_message"),
            finished_at=row.get("finished_at"),
        )


class MySQLKnowledgeRuntimeBackend(MySQLKnowledgeMetadataBackend):
    SOURCE_TABLE = "knowledge_runtime_sources"
    RUNTIME_DOCUMENT_TABLE = "knowledge_runtime_documents"
    CHUNK_TABLE = "knowledge_runtime_chunks"
    INGESTION_TABLE = "knowledge_runtime_ingestions"

    def _ensure_schema(self, cursor) -> None:
        super()._ensure_schema(cursor)
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.SOURCE_TABLE}` (
              source_id VARCHAR(64) PRIMARY KEY,
              name VARCHAR(255) NOT NULL,
              kind VARCHAR(64) NOT NULL,
              uri LONGTEXT NULL,
              tags_json LONGTEXT NOT NULL,
              document_count INT NOT NULL,
              chunk_count INT NOT NULL,
              created_at VARCHAR(64) NOT NULL,
              updated_at VARCHAR(64) NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.RUNTIME_DOCUMENT_TABLE}` (
              doc_id VARCHAR(64) PRIMARY KEY,
              source_id VARCHAR(64) NOT NULL,
              title VARCHAR(255) NOT NULL,
              content LONGTEXT NOT NULL,
              tags_json LONGTEXT NOT NULL,
              language VARCHAR(64) NOT NULL,
              checksum VARCHAR(64) NOT NULL,
              chunk_ids_json LONGTEXT NOT NULL,
              created_at VARCHAR(64) NOT NULL,
              updated_at VARCHAR(64) NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.CHUNK_TABLE}` (
              chunk_id VARCHAR(64) PRIMARY KEY,
              source_id VARCHAR(64) NOT NULL,
              document_id VARCHAR(64) NOT NULL,
              document_title VARCHAR(255) NOT NULL,
              ordinal INT NOT NULL,
              content LONGTEXT NOT NULL,
              token_estimate INT NOT NULL,
              keywords_json LONGTEXT NOT NULL,
              tags_json LONGTEXT NOT NULL,
              created_at VARCHAR(64) NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.INGESTION_TABLE}` (
              ingestion_id VARCHAR(64) PRIMARY KEY,
              source_id VARCHAR(64) NOT NULL,
              document_id VARCHAR(64) NOT NULL,
              status VARCHAR(64) NOT NULL,
              documents_received INT NOT NULL,
              chunks_created INT NOT NULL,
              warnings_json LONGTEXT NOT NULL,
              created_at VARCHAR(64) NOT NULL,
              completed_at VARCHAR(64) NOT NULL
            )
            """
        )

    def sync_runtime_from_local(
        self,
        *,
        sources: list[KnowledgeSource],
        documents: list[KnowledgeDocument],
        chunks: list[KnowledgeChunk],
        ingestions: list[IngestionJob],
    ) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                for source in sources:
                    self._upsert_source(cursor, source)
                for document in documents:
                    self._upsert_runtime_document(cursor, document)
                if documents:
                    document_ids = [document.id for document in documents]
                    cursor.execute(
                        f"DELETE FROM `{self.CHUNK_TABLE}` WHERE document_id IN ({', '.join(['%s'] * len(document_ids))})",
                        tuple(document_ids),
                    )
                for chunk in chunks:
                    self._upsert_chunk(cursor, chunk)
                for ingestion in ingestions:
                    self._upsert_ingestion_job(cursor, ingestion)
            connection.commit()
        finally:
            connection.close()

    def load_runtime_state(self) -> KnowledgeRuntimeState:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT source_id, name, kind, uri, tags_json, document_count, chunk_count, created_at, updated_at
                    FROM `{self.SOURCE_TABLE}`
                    """
                )
                source_rows = cursor.fetchall() or []
                cursor.execute(
                    f"""
                    SELECT doc_id, source_id, title, content, tags_json, language, checksum, chunk_ids_json, created_at, updated_at
                    FROM `{self.RUNTIME_DOCUMENT_TABLE}`
                    """
                )
                document_rows = cursor.fetchall() or []
                cursor.execute(
                    f"""
                    SELECT chunk_id, source_id, document_id, document_title, ordinal, content, token_estimate,
                           keywords_json, tags_json, created_at
                    FROM `{self.CHUNK_TABLE}`
                    ORDER BY document_id, ordinal, chunk_id
                    """
                )
                chunk_rows = cursor.fetchall() or []
                cursor.execute(
                    f"""
                    SELECT ingestion_id, source_id, document_id, status, documents_received, chunks_created,
                           warnings_json, created_at, completed_at
                    FROM `{self.INGESTION_TABLE}`
                    """
                )
                ingestion_rows = cursor.fetchall() or []
        finally:
            connection.close()

        return KnowledgeRuntimeState(
            sources=[self._build_source(row) for row in source_rows],
            documents=[self._build_runtime_document(row) for row in document_rows],
            chunks=[self._build_chunk(row) for row in chunk_rows],
            ingestions=[self._build_ingestion_job(row) for row in ingestion_rows],
        )

    def upsert_source(self, source: KnowledgeSource) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                self._upsert_source(cursor, source)
            connection.commit()
        finally:
            connection.close()

    def upsert_document(self, document: KnowledgeDocument) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                self._upsert_runtime_document(cursor, document)
            connection.commit()
        finally:
            connection.close()

    def replace_document_chunks(self, document_id: str, chunks: list[KnowledgeChunk]) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"DELETE FROM `{self.CHUNK_TABLE}` WHERE document_id = %s",
                    (document_id,),
                )
                for chunk in chunks:
                    self._upsert_chunk(cursor, chunk)
            connection.commit()
        finally:
            connection.close()

    def upsert_ingestion_job(self, job: IngestionJob) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                self._upsert_ingestion_job(cursor, job)
            connection.commit()
        finally:
            connection.close()

    def _upsert_source(self, cursor, source: KnowledgeSource) -> None:
        cursor.execute(
            f"""
            INSERT INTO `{self.SOURCE_TABLE}` (
              source_id, name, kind, uri, tags_json, document_count, chunk_count, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              name = VALUES(name),
              kind = VALUES(kind),
              uri = VALUES(uri),
              tags_json = VALUES(tags_json),
              document_count = VALUES(document_count),
              chunk_count = VALUES(chunk_count),
              created_at = VALUES(created_at),
              updated_at = VALUES(updated_at)
            """,
            (
                source.id,
                source.name,
                source.kind,
                source.uri,
                json.dumps(source.tags, ensure_ascii=False),
                source.document_count,
                source.chunk_count,
                source.created_at,
                source.updated_at,
            ),
        )

    @staticmethod
    def _build_source(row: dict[str, object]) -> KnowledgeSource:
        return KnowledgeSource(
            id=str(row["source_id"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            uri=row.get("uri"),
            tags=json.loads(row["tags_json"]) if row.get("tags_json") else [],
            document_count=int(row["document_count"]),
            chunk_count=int(row["chunk_count"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _upsert_runtime_document(self, cursor, document: KnowledgeDocument) -> None:
        cursor.execute(
            f"""
            INSERT INTO `{self.RUNTIME_DOCUMENT_TABLE}` (
              doc_id, source_id, title, content, tags_json, language, checksum, chunk_ids_json, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              source_id = VALUES(source_id),
              title = VALUES(title),
              content = VALUES(content),
              tags_json = VALUES(tags_json),
              language = VALUES(language),
              checksum = VALUES(checksum),
              chunk_ids_json = VALUES(chunk_ids_json),
              created_at = VALUES(created_at),
              updated_at = VALUES(updated_at)
            """,
            (
                document.id,
                document.source_id,
                document.title,
                document.content,
                json.dumps(document.tags, ensure_ascii=False),
                document.language,
                document.checksum,
                json.dumps(document.chunk_ids, ensure_ascii=False),
                document.created_at,
                document.updated_at,
            ),
        )

    @staticmethod
    def _build_runtime_document(row: dict[str, object]) -> KnowledgeDocument:
        return KnowledgeDocument(
            id=str(row["doc_id"]),
            source_id=str(row["source_id"]),
            title=str(row["title"]),
            content=str(row["content"]),
            tags=json.loads(row["tags_json"]) if row.get("tags_json") else [],
            language=str(row["language"]),
            checksum=str(row["checksum"]),
            chunk_ids=json.loads(row["chunk_ids_json"]) if row.get("chunk_ids_json") else [],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _upsert_chunk(self, cursor, chunk: KnowledgeChunk) -> None:
        cursor.execute(
            f"""
            INSERT INTO `{self.CHUNK_TABLE}` (
              chunk_id, source_id, document_id, document_title, ordinal, content, token_estimate, keywords_json, tags_json, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              source_id = VALUES(source_id),
              document_id = VALUES(document_id),
              document_title = VALUES(document_title),
              ordinal = VALUES(ordinal),
              content = VALUES(content),
              token_estimate = VALUES(token_estimate),
              keywords_json = VALUES(keywords_json),
              tags_json = VALUES(tags_json),
              created_at = VALUES(created_at)
            """,
            (
                chunk.id,
                chunk.source_id,
                chunk.document_id,
                chunk.document_title,
                chunk.ordinal,
                chunk.content,
                chunk.token_estimate,
                json.dumps(chunk.keywords, ensure_ascii=False),
                json.dumps(chunk.tags, ensure_ascii=False),
                chunk.created_at,
            ),
        )

    @staticmethod
    def _build_chunk(row: dict[str, object]) -> KnowledgeChunk:
        return KnowledgeChunk(
            id=str(row["chunk_id"]),
            source_id=str(row["source_id"]),
            document_id=str(row["document_id"]),
            document_title=str(row["document_title"]),
            ordinal=int(row["ordinal"]),
            content=str(row["content"]),
            token_estimate=int(row["token_estimate"]),
            keywords=json.loads(row["keywords_json"]) if row.get("keywords_json") else [],
            tags=json.loads(row["tags_json"]) if row.get("tags_json") else [],
            created_at=str(row["created_at"]),
        )

    def _upsert_ingestion_job(self, cursor, job: IngestionJob) -> None:
        cursor.execute(
            f"""
            INSERT INTO `{self.INGESTION_TABLE}` (
              ingestion_id, source_id, document_id, status, documents_received, chunks_created, warnings_json, created_at, completed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              source_id = VALUES(source_id),
              document_id = VALUES(document_id),
              status = VALUES(status),
              documents_received = VALUES(documents_received),
              chunks_created = VALUES(chunks_created),
              warnings_json = VALUES(warnings_json),
              created_at = VALUES(created_at),
              completed_at = VALUES(completed_at)
            """,
            (
                job.id,
                job.source_id,
                job.document_id,
                job.status,
                job.documents_received,
                job.chunks_created,
                json.dumps(job.warnings, ensure_ascii=False),
                job.created_at,
                job.completed_at,
            ),
        )

    @staticmethod
    def _build_ingestion_job(row: dict[str, object]) -> IngestionJob:
        return IngestionJob(
            id=str(row["ingestion_id"]),
            source_id=str(row["source_id"]),
            document_id=str(row["document_id"]),
            status=str(row["status"]),
            documents_received=int(row["documents_received"]),
            chunks_created=int(row["chunks_created"]),
            warnings=json.loads(row["warnings_json"]) if row.get("warnings_json") else [],
            created_at=str(row["created_at"]),
            completed_at=str(row["completed_at"]),
        )
