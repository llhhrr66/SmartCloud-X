from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from app.models.admin import AdminAsyncJob, KnowledgeBaseProfile, KnowledgeDocumentProfile

try:
    import pymysql
except ImportError:  # pragma: no cover - exercised in integration environments
    pymysql = None


@dataclass(frozen=True)
class KnowledgeMetadataState:
    knowledge_base_profiles: list[KnowledgeBaseProfile]
    document_profiles: list[KnowledgeDocumentProfile]
    admin_jobs: list[AdminAsyncJob]


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
