import json
from collections import defaultdict
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, Field

from app.models.admin import AdminAsyncJob, KnowledgeBaseProfile, KnowledgeDocumentProfile
from app.models.knowledge import (
    IngestionJob,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    SourceSeed,
)


class StoreState(BaseModel):
    sources: dict[str, KnowledgeSource] = Field(default_factory=dict)
    documents: dict[str, KnowledgeDocument] = Field(default_factory=dict)
    chunks: dict[str, KnowledgeChunk] = Field(default_factory=dict)
    ingestions: dict[str, IngestionJob] = Field(default_factory=dict)
    knowledge_base_profiles: dict[str, KnowledgeBaseProfile] = Field(default_factory=dict)
    document_profiles: dict[str, KnowledgeDocumentProfile] = Field(default_factory=dict)
    admin_jobs: dict[str, AdminAsyncJob] = Field(default_factory=dict)


def _slugify(value: str, fallback: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in value.strip())
    normalized = "-".join(part for part in cleaned.split("-") if part)
    return normalized or fallback


def _pick_first_non_empty(values: list[str | None], fallback: str | None = None) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _max_timestamp(values: list[str | None], fallback: str) -> str:
    timestamps = [value for value in values if isinstance(value, str) and value.strip()]
    if not timestamps:
        return fallback
    return max(timestamps)


def _min_timestamp(values: list[str | None], fallback: str) -> str:
    timestamps = [value for value in values if isinstance(value, str) and value.strip()]
    if not timestamps:
        return fallback
    return min(timestamps)


class KnowledgeStoreRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> StoreState:
        if not self.path.exists():
            return StoreState()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return StoreState.model_validate(payload)

    def _persist(self) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self._state.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def list_sources(self) -> list[KnowledgeSource]:
        with self._lock:
            return sorted(self._state.sources.values(), key=lambda item: item.updated_at, reverse=True)

    def get_source(self, source_id: str) -> KnowledgeSource | None:
        with self._lock:
            return self._state.sources.get(source_id)

    def get_knowledge_base_profile(self, kb_id: str) -> KnowledgeBaseProfile | None:
        with self._lock:
            return self._state.knowledge_base_profiles.get(kb_id)

    def find_knowledge_base_profile_by_code(self, code: str) -> KnowledgeBaseProfile | None:
        normalized_code = code.strip().lower()
        with self._lock:
            for profile in self._state.knowledge_base_profiles.values():
                if profile.code.strip().lower() == normalized_code:
                    return profile
        return None

    def list_knowledge_base_profiles(self) -> list[KnowledgeBaseProfile]:
        with self._lock:
            return list(self._state.knowledge_base_profiles.values())

    def save_knowledge_base_profile(self, profile: KnowledgeBaseProfile) -> KnowledgeBaseProfile:
        with self._lock:
            self._state.knowledge_base_profiles[profile.kb_id] = profile
            self._persist()
            return profile

    def get_document(self, document_id: str) -> KnowledgeDocument | None:
        with self._lock:
            return self._state.documents.get(document_id)

    def get_document_profile(self, document_id: str) -> KnowledgeDocumentProfile | None:
        with self._lock:
            return self._state.document_profiles.get(document_id)

    def save_document_profile(self, profile: KnowledgeDocumentProfile) -> KnowledgeDocumentProfile:
        with self._lock:
            self._state.document_profiles[profile.doc_id] = profile
            self._persist()
            return profile

    def get_admin_job(self, job_id: str) -> AdminAsyncJob | None:
        with self._lock:
            return self._state.admin_jobs.get(job_id)

    def save_admin_job(self, job: AdminAsyncJob) -> AdminAsyncJob:
        with self._lock:
            self._state.admin_jobs[job.job_id] = job
            self._persist()
            return job

    def list_admin_jobs(self) -> list[AdminAsyncJob]:
        with self._lock:
            jobs = list(self._state.admin_jobs.values())
        return sorted(
            jobs,
            key=lambda item: (item.finished_at or item.created_at, item.created_at),
            reverse=True,
        )

    def list_document_profiles(self, kb_id: str | None = None) -> list[KnowledgeDocumentProfile]:
        with self._lock:
            profiles = list(self._state.document_profiles.values())
        if kb_id:
            profiles = [profile for profile in profiles if profile.kb_id == kb_id]
        return profiles

    def find_source_by_seed(self, seed: SourceSeed) -> KnowledgeSource | None:
        normalized_name = seed.name.strip().lower()
        normalized_uri = seed.uri.strip() if seed.uri else None
        with self._lock:
            for source in self._state.sources.values():
                if source.name.strip().lower() != normalized_name:
                    continue
                if source.kind != seed.kind:
                    continue
                if (source.uri.strip() if source.uri else None) != normalized_uri:
                    continue
                return source
        return None

    def save_source(self, source: KnowledgeSource) -> KnowledgeSource:
        with self._lock:
            self._state.sources[source.id] = source
            self._persist()
            return source

    def reconcile_runtime_state(self) -> dict[str, int]:
        repaired = {
            "sources": 0,
            "knowledgeBaseProfiles": 0,
            "documentProfiles": 0,
        }
        with self._lock:
            documents_by_source: dict[str, list[KnowledgeDocument]] = defaultdict(list)
            chunks_by_source: dict[str, list[KnowledgeChunk]] = defaultdict(list)
            latest_job_by_document: dict[str, IngestionJob] = {}

            for document in self._state.documents.values():
                documents_by_source[document.source_id].append(document)
            for chunk in self._state.chunks.values():
                chunks_by_source[chunk.source_id].append(chunk)
            for job in self._state.ingestions.values():
                previous = latest_job_by_document.get(job.document_id)
                if previous is None or (job.completed_at, job.created_at, job.id) > (
                    previous.completed_at,
                    previous.created_at,
                    previous.id,
                ):
                    latest_job_by_document[job.document_id] = job

            normalized_kb_profiles: dict[str, KnowledgeBaseProfile] = {}
            kb_profile_candidates: dict[str, list[KnowledgeBaseProfile]] = defaultdict(list)
            for profile_key, profile in list(self._state.knowledge_base_profiles.items()):
                if self._state.sources.get(profile.kb_id) is None:
                    repaired["knowledgeBaseProfiles"] += 1
                    continue
                kb_profile_candidates[profile.kb_id].append(profile)
                if profile_key != profile.kb_id:
                    repaired["knowledgeBaseProfiles"] += 1

            for source_id, source in list(self._state.sources.items()):
                source_documents = documents_by_source.get(source_id, [])
                candidates = sorted(
                    kb_profile_candidates.get(source_id, []),
                    key=lambda item: (
                        item.updated_at,
                        item.created_at,
                        item.code,
                        item.retrieval_mode,
                    ),
                    reverse=True,
                )
                fallback_code = _slugify((source.uri or source.name).replace("kb://", ""), source.id)
                merged_profile = KnowledgeBaseProfile(
                    kb_id=source.id,
                    code=_pick_first_non_empty(
                        [candidate.code for candidate in candidates],
                        fallback_code,
                    )
                    or fallback_code,
                    scene=_pick_first_non_empty(
                        [candidate.scene for candidate in candidates],
                        source.kind,
                    )
                    or source.kind,
                    language=_pick_first_non_empty(
                        [candidate.language for candidate in candidates],
                        source_documents[0].language if source_documents else "zh-CN",
                    )
                    or "zh-CN",
                    retrieval_mode=_pick_first_non_empty(
                        [candidate.retrieval_mode for candidate in candidates],
                        "hybrid-baseline",
                    )
                    or "hybrid-baseline",
                    embedding_model=_pick_first_non_empty(
                        [candidate.embedding_model for candidate in candidates],
                        "baseline-keyword",
                    )
                    or "baseline-keyword",
                    status=_pick_first_non_empty(
                        [candidate.status for candidate in candidates],
                        "ready",
                    )
                    or "ready",
                    created_at=_min_timestamp(
                        [source.created_at] + [candidate.created_at for candidate in candidates],
                        source.created_at,
                    ),
                    updated_at=_max_timestamp(
                        [source.updated_at] + [candidate.updated_at for candidate in candidates],
                        source.updated_at,
                    ),
                )
                normalized_kb_profiles[source_id] = merged_profile
                if len(candidates) != 1 or (candidates and candidates[0] != merged_profile):
                    repaired["knowledgeBaseProfiles"] += 1

            if normalized_kb_profiles != self._state.knowledge_base_profiles:
                self._state.knowledge_base_profiles = normalized_kb_profiles

            normalized_document_profiles: dict[str, KnowledgeDocumentProfile] = {}
            document_profile_candidates: dict[str, list[KnowledgeDocumentProfile]] = defaultdict(list)
            for profile_key, profile in list(self._state.document_profiles.items()):
                if self._state.documents.get(profile.doc_id) is None:
                    repaired["documentProfiles"] += 1
                    continue
                document_profile_candidates[profile.doc_id].append(profile)
                if profile_key != profile.doc_id:
                    repaired["documentProfiles"] += 1

            mutated = False
            if repaired["knowledgeBaseProfiles"] > 0 or repaired["documentProfiles"] > 0:
                mutated = True
            for source_id, source in list(self._state.sources.items()):
                source_documents = documents_by_source.get(source_id, [])
                actual_document_count = len(source_documents)
                actual_chunk_count = len(chunks_by_source.get(source_id, []))
                latest_document_at = max(
                    [source.updated_at] + [document.updated_at for document in source_documents]
                )
                if (
                    source.document_count != actual_document_count
                    or source.chunk_count != actual_chunk_count
                    or source.updated_at != latest_document_at
                ):
                    self._state.sources[source_id] = source.model_copy(
                        update={
                            "document_count": actual_document_count,
                            "chunk_count": actual_chunk_count,
                            "updated_at": latest_document_at,
                        }
                    )
                    source = self._state.sources[source_id]
                    repaired["sources"] += 1
                    mutated = True

                profile = normalized_kb_profiles.get(source_id)
                if profile is None:
                    fallback_code = _slugify(
                        (source.uri or source.name).replace("kb://", ""),
                        source.id,
                    )
                    fallback_language = source_documents[0].language if source_documents else "zh-CN"
                    normalized_kb_profiles[source_id] = KnowledgeBaseProfile(
                        kb_id=source.id,
                        code=fallback_code,
                        scene=source.kind,
                        language=fallback_language,
                        retrieval_mode="hybrid-baseline",
                        embedding_model="baseline-keyword",
                        status="ready",
                        created_at=source.created_at,
                        updated_at=source.updated_at,
                    )
                    repaired["knowledgeBaseProfiles"] += 1
                    mutated = True
                else:
                    profile_updates: dict[str, str] = {}
                    if not profile.code.strip():
                        profile_updates["code"] = _slugify(
                            (source.uri or source.name).replace("kb://", ""),
                            source.id,
                        )
                    if not profile.scene.strip():
                        profile_updates["scene"] = source.kind
                    if not profile.language.strip():
                        profile_updates["language"] = (
                            source_documents[0].language if source_documents else "zh-CN"
                        )
                    updated_at = max(profile.updated_at, source.updated_at)
                    if updated_at != profile.updated_at:
                        profile_updates["updated_at"] = updated_at
                    if profile_updates:
                        normalized_kb_profiles[source_id] = profile.model_copy(update=profile_updates)
                        repaired["knowledgeBaseProfiles"] += 1
                        mutated = True

            for document_id, document in list(self._state.documents.items()):
                candidates = sorted(
                    document_profile_candidates.get(document_id, []),
                    key=lambda item: (
                        item.version_no,
                        item.indexed_at or "",
                        1 if item.file_id else 0,
                        1 if item.source_type and item.source_type != "inline" else 0,
                        item.latest_job_id or "",
                    ),
                    reverse=True,
                )
                latest_job = latest_job_by_document.get(document_id)
                source = self._state.sources.get(document.source_id)
                primary = candidates[0] if candidates else None
                merged_profile = KnowledgeDocumentProfile(
                    doc_id=document.id,
                    kb_id=document.source_id,
                    status=primary.status if primary is not None else "active",
                    parse_status=primary.parse_status if primary is not None else "completed",
                    index_status=primary.index_status if primary is not None else "ready",
                    version_no=max(
                        1,
                        max((candidate.version_no for candidate in candidates), default=1),
                    ),
                    file_id=_pick_first_non_empty(
                        [candidate.file_id for candidate in candidates],
                        primary.file_id if primary is not None else None,
                    ),
                    source_type=(
                        _pick_first_non_empty(
                            [
                                candidate.source_type
                                for candidate in candidates
                                if candidate.source_type and candidate.source_type != "inline"
                            ],
                            None,
                        )
                        or (primary.source_type if primary is not None and primary.source_type else None)
                        or "inline"
                    ),
                    source_uri=(
                        _pick_first_non_empty(
                            [candidate.source_uri for candidate in candidates],
                            primary.source_uri if primary is not None else None,
                        )
                        or (source.uri if source else None)
                    ),
                    indexed_at=_max_timestamp(
                        [document.updated_at]
                        + [candidate.indexed_at for candidate in candidates]
                        + ([latest_job.completed_at] if latest_job is not None else []),
                        document.updated_at,
                    ),
                    error_message=primary.error_message if primary is not None else None,
                    latest_job_id=latest_job.id if latest_job else (
                        _pick_first_non_empty(
                            [candidate.latest_job_id for candidate in candidates],
                            None,
                        )
                    ),
                )
                if primary is None:
                    normalized_document_profiles[document_id] = merged_profile
                    repaired["documentProfiles"] += 1
                    mutated = True
                    continue

                normalized_document_profiles[document_id] = merged_profile
                if len(candidates) != 1 or (primary is not None and primary != merged_profile):
                    repaired["documentProfiles"] += 1
                    mutated = True

            if normalized_document_profiles != self._state.document_profiles:
                self._state.document_profiles = normalized_document_profiles
            if normalized_kb_profiles != self._state.knowledge_base_profiles:
                self._state.knowledge_base_profiles = normalized_kb_profiles
            if mutated:
                self._persist()
        return repaired

    def save_document(
        self,
        document: KnowledgeDocument,
        chunks: list[KnowledgeChunk],
        job: IngestionJob,
        source: KnowledgeSource,
    ) -> None:
        with self._lock:
            self._state.sources[source.id] = source
            self._state.documents[document.id] = document
            self._state.ingestions[job.id] = job
            for chunk in chunks:
                self._state.chunks[chunk.id] = chunk
            self._persist()

    def replace_document_chunks(
        self,
        document: KnowledgeDocument,
        chunks: list[KnowledgeChunk],
        job: IngestionJob,
        source: KnowledgeSource,
    ) -> None:
        with self._lock:
            previous = self._state.documents.get(document.id)
            if previous is not None:
                for chunk_id in previous.chunk_ids:
                    self._state.chunks.pop(chunk_id, None)
            self._state.sources[source.id] = source
            self._state.documents[document.id] = document
            self._state.ingestions[job.id] = job
            for chunk in chunks:
                self._state.chunks[chunk.id] = chunk
            self._persist()

    def save_ingestion_job(self, job: IngestionJob) -> None:
        with self._lock:
            self._state.ingestions[job.id] = job
            self._persist()

    def find_document(self, source_id: str, checksum: str, title: str) -> KnowledgeDocument | None:
        normalized_title = title.strip()
        with self._lock:
            for document in self._state.documents.values():
                if document.source_id != source_id:
                    continue
                if document.checksum != checksum:
                    continue
                if document.title.strip() != normalized_title:
                    continue
                return document
        return None

    def list_documents(self, source_id: str | None = None) -> list[KnowledgeDocument]:
        with self._lock:
            documents = list(self._state.documents.values())
        if source_id:
            documents = [document for document in documents if document.source_id == source_id]
        return sorted(documents, key=lambda item: item.updated_at, reverse=True)

    def list_chunks(
        self,
        document_id: str | None = None,
        source_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> list[KnowledgeChunk]:
        with self._lock:
            chunks = list(self._state.chunks.values())
        if document_id:
            chunks = [chunk for chunk in chunks if chunk.document_id == document_id]
        if source_ids:
            source_set = set(source_ids)
            chunks = [chunk for chunk in chunks if chunk.source_id in source_set]
        if tags:
            tag_set = set(tag.lower() for tag in tags)
            chunks = [
                chunk
                for chunk in chunks
                if tag_set.intersection(tag.lower() for tag in chunk.tags)
            ]
        if document_id:
            return sorted(chunks, key=lambda item: item.ordinal)
        return sorted(chunks, key=lambda item: (item.created_at, item.ordinal), reverse=True)

    def list_ingestions(self, source_id: str | None = None) -> list[IngestionJob]:
        with self._lock:
            ingestions = list(self._state.ingestions.values())
        if source_id:
            ingestions = [job for job in ingestions if job.source_id == source_id]
        return sorted(ingestions, key=lambda item: item.created_at, reverse=True)

    def snapshot_counts(self) -> dict[str, int]:
        with self._lock:
            return {
                "sources": len(self._state.sources),
                "documents": len(self._state.documents),
                "chunks": len(self._state.chunks),
                "ingestions": len(self._state.ingestions),
                "knowledgeBases": len(self._state.knowledge_base_profiles),
                "documentProfiles": len(self._state.document_profiles),
                "adminJobs": len(self._state.admin_jobs),
            }
