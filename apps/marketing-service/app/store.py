from __future__ import annotations

import hashlib
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from threading import RLock
from uuid import uuid4
from urllib.parse import urlencode

from app.core.config import get_settings
from app.models import (
    CreatePosterTaskRequest,
    MarketingCampaign,
    MarketingCampaignListData,
    MarketingCampaignRecord,
    MarketingCopyListData,
    MarketingCopyRequest,
    MarketingCopyResult,
    MarketingStoreSnapshot,
    PosterIdempotencyRecord,
    PosterTaskCreateResponseData,
    PosterTaskListData,
    PosterTaskRecord,
    PromotionLinkListData,
    PromotionLinkRequest,
    PromotionLinkResult,
    ServiceError,
    StoredMarketingCopy,
    StoredPromotionLink,
    now_iso,
    utc_now,
)


class MarketingStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._lock = RLock()
        self._snapshot = self._load()

    def _load(self) -> MarketingStoreSnapshot:
        if self.file_path.exists():
            return MarketingStoreSnapshot.model_validate_json(self.file_path.read_text(encoding="utf-8"))
        snapshot = self._default_snapshot()
        self._persist(snapshot)
        return snapshot

    def _persist(self, snapshot: MarketingStoreSnapshot | None = None) -> None:
        with self._lock:
            target = snapshot or self._snapshot
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_path.write_text(target.model_dump_json(indent=2), encoding="utf-8")

    def _default_snapshot(self) -> MarketingStoreSnapshot:
        return MarketingStoreSnapshot(
            campaigns=[
                MarketingCampaignRecord(
                    campaign_id="cmp_gpu_launch_001",
                    name="GPU 云主机上新季",
                    product_type="gpu",
                    status="published",
                    start_at="2026-04-01T00:00:00+00:00",
                    end_at="2026-05-31T23:59:59+00:00",
                    landing_page_url="https://smartcloud.local/campaigns/gpu-spring",
                    highlights=["新品首发", "AI 算力", "弹性扩容"],
                ),
                MarketingCampaignRecord(
                    campaign_id="cmp_ecs_growth_001",
                    name="弹性云服务器增长计划",
                    product_type="ecs",
                    status="published",
                    start_at="2026-03-15T00:00:00+00:00",
                    end_at="2026-06-30T23:59:59+00:00",
                    landing_page_url="https://smartcloud.local/campaigns/ecs-growth",
                    highlights=["稳定上云", "成本可控", "企业通用"],
                ),
                MarketingCampaignRecord(
                    campaign_id="cmp_storage_draft_001",
                    name="对象存储体验周",
                    product_type="storage",
                    status="draft",
                    start_at="2026-06-01T00:00:00+00:00",
                    end_at="2026-06-30T23:59:59+00:00",
                    landing_page_url="https://smartcloud.local/campaigns/storage-week",
                    highlights=["草稿活动"],
                ),
            ]
        )

    def clear(self) -> None:
        with self._lock:
            self._snapshot = self._default_snapshot()
            self._persist()

    def list_campaigns(
        self,
        *,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        status: str | None,
        product_type: str | None,
    ) -> MarketingCampaignListData:
        with self._lock:
            current_time = utc_now()
            campaigns = [
                item
                for item in self._snapshot.campaigns
                if self._is_user_visible_campaign(item, current_time=current_time)
            ]
            if status:
                campaigns = [item for item in campaigns if item.status == status]
            if product_type:
                campaigns = [item for item in campaigns if item.product_type == product_type]
            reverse = sort_order != "asc"
            sort_field = sort_by if sort_by in {"start_at", "end_at", "name", "product_type", "status"} else "start_at"
            campaigns.sort(key=lambda item: getattr(item, sort_field), reverse=reverse)
            total = len(campaigns)
            start = (page - 1) * page_size
            end = start + page_size
            items = campaigns[start:end]
            total_pages = (total + page_size - 1) // page_size if total else 0
            return MarketingCampaignListData(
                items=[MarketingCampaign.model_validate(item.model_dump()) for item in items],
                page=page,
                page_size=page_size,
                total=total,
                total_pages=total_pages,
                sort_by=sort_field,
                sort_order="desc" if reverse else "asc",
            )

    def create_copy(self, *, user_id: str, tenant_id: str | None, payload: MarketingCopyRequest) -> MarketingCopyResult:
        with self._lock:
            campaign = self._get_user_visible_campaign(payload.campaign_id)
            if campaign is None:
                raise ServiceError(404, 4040001, f"marketing campaign '{payload.campaign_id}' was not found")
            keywords = payload.keywords or campaign.highlights or ["稳定上云", "弹性扩容", "成本可控"]
            headline_prefix = {
                "launch": "新品首发",
                "growth": "增长加速",
                "professional": "企业上云",
            }[payload.tone]
            result = StoredMarketingCopy(
                user_id=user_id,
                tenant_id=tenant_id,
                copy_id=f"copy_{uuid4().hex[:12]}",
                campaign_id=campaign.campaign_id,
                campaign_name=campaign.name,
                topic=payload.topic,
                audience=payload.audience,
                tone=payload.tone,
                headline=f"{headline_prefix}｜{payload.topic}",
                summary=f"面向{payload.audience}，突出{'、'.join(keywords[:2])}等核心卖点。",
                body="\n\n".join(
                    [
                        f"{campaign.name}现已开放，围绕“{payload.topic}”提供更贴近业务落地的推广素材。",
                        f"重点强调 {'、'.join(keywords)}，帮助{payload.audience}快速理解活动价值与适用场景。",
                        "建议将该文案用于落地页首屏、社群推送或销售跟进话术，并结合海报任务统一视觉输出。",
                    ]
                ),
                call_to_action="立即预约新品权益" if payload.tone == "launch" else "立即领取活动方案",
                keywords=keywords,
                landing_page_url=campaign.landing_page_url,
                created_at=now_iso(),
            )
            self._snapshot.generated_copies.append(result)
            self._persist()
            return MarketingCopyResult.model_validate(result.model_dump())

    def get_copy(self, *, user_id: str, tenant_id: str | None, copy_id: str) -> MarketingCopyResult | None:
        with self._lock:
            record = next(
                (
                    item
                    for item in self._snapshot.generated_copies
                    if item.user_id == user_id
                    and _tenant_scope_matches(item.tenant_id, tenant_id)
                    and item.copy_id == copy_id
                ),
                None,
            )
            if record is None:
                return None
            return MarketingCopyResult.model_validate(record.model_dump())

    def list_copies(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        campaign_id: str | None,
        tone: str | None,
    ) -> MarketingCopyListData:
        with self._lock:
            copies = [
                item
                for item in self._snapshot.generated_copies
                if item.user_id == user_id and _tenant_scope_matches(item.tenant_id, tenant_id)
            ]
            if campaign_id:
                copies = [item for item in copies if item.campaign_id == campaign_id]
            if tone:
                copies = [item for item in copies if item.tone == tone]
            reverse = sort_order != "asc"
            sort_field = sort_by if sort_by in {"created_at", "topic", "campaign_name", "tone"} else "created_at"
            copies.sort(key=lambda item: getattr(item, sort_field) or "", reverse=reverse)
            total = len(copies)
            start = (page - 1) * page_size
            end = start + page_size
            items = [MarketingCopyResult.model_validate(item.model_dump()) for item in copies[start:end]]
            total_pages = (total + page_size - 1) // page_size if total else 0
            return MarketingCopyListData(
                items=items,
                page=page,
                page_size=page_size,
                total=total,
                total_pages=total_pages,
                sort_by=sort_field,
                sort_order="desc" if reverse else "asc",
            )

    def create_promotion_link(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        payload: PromotionLinkRequest,
    ) -> PromotionLinkResult:
        with self._lock:
            campaign = self._get_user_visible_campaign(payload.campaign_id)
            if campaign is None:
                raise ServiceError(404, 4040001, f"marketing campaign '{payload.campaign_id}' was not found")
            tracking_params = {
                "utm_campaign": campaign.campaign_id,
                "utm_source": payload.source or payload.channel,
            }
            if payload.content_tag:
                tracking_params["utm_content"] = payload.content_tag
            tracking_code = urlencode(tracking_params)
            result = StoredPromotionLink(
                user_id=user_id,
                tenant_id=tenant_id,
                link_id=f"plink_{uuid4().hex[:12]}",
                campaign_id=campaign.campaign_id,
                campaign_name=campaign.name,
                channel=payload.channel,
                short_url=f"https://go.smartcloud.local/{uuid4().hex[:8]}",
                landing_page_url=f"{campaign.landing_page_url}?{tracking_code}",
                tracking_code=tracking_code,
                created_at=now_iso(),
                note="baseline placeholder promotion link; replace short-domain routing in production",
            )
            self._snapshot.promotion_links.append(result)
            self._persist()
            return PromotionLinkResult.model_validate(result.model_dump())

    def get_promotion_link(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        link_id: str,
    ) -> PromotionLinkResult | None:
        with self._lock:
            record = next(
                (
                    item
                    for item in self._snapshot.promotion_links
                    if item.user_id == user_id
                    and _tenant_scope_matches(item.tenant_id, tenant_id)
                    and item.link_id == link_id
                ),
                None,
            )
            if record is None:
                return None
            return PromotionLinkResult.model_validate(record.model_dump())

    def list_promotion_links(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        campaign_id: str | None,
        channel: str | None,
    ) -> PromotionLinkListData:
        with self._lock:
            links = [
                item
                for item in self._snapshot.promotion_links
                if item.user_id == user_id and _tenant_scope_matches(item.tenant_id, tenant_id)
            ]
            if campaign_id:
                links = [item for item in links if item.campaign_id == campaign_id]
            if channel:
                links = [item for item in links if item.channel == channel]
            reverse = sort_order != "asc"
            sort_field = sort_by if sort_by in {"created_at", "campaign_name", "channel"} else "created_at"
            links.sort(key=lambda item: getattr(item, sort_field) or "", reverse=reverse)
            total = len(links)
            start = (page - 1) * page_size
            end = start + page_size
            items = [PromotionLinkResult.model_validate(item.model_dump()) for item in links[start:end]]
            total_pages = (total + page_size - 1) // page_size if total else 0
            return PromotionLinkListData(
                items=items,
                page=page,
                page_size=page_size,
                total=total,
                total_pages=total_pages,
                sort_by=sort_field,
                sort_order="desc" if reverse else "asc",
            )

    def create_poster_task(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        payload: CreatePosterTaskRequest,
        idempotency_key: str | None,
    ) -> PosterTaskCreateResponseData:
        campaign = self._get_user_visible_campaign(payload.campaign_id)
        if campaign is None:
            raise ServiceError(404, 4040001, f"marketing campaign '{payload.campaign_id}' was not found")
        normalized_payload = json.dumps(payload.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        payload_hash = _payload_hash(user_id=user_id, tenant_id=tenant_id, normalized_payload=normalized_payload)
        legacy_payload_hash = _legacy_payload_hash(user_id=user_id, normalized_payload=normalized_payload)
        estimated_seconds = get_settings().default_estimated_seconds
        with self._lock:
            if idempotency_key:
                existing = next(
                    (
                        item
                        for item in self._snapshot.poster_idempotency_records
                        if item.key == idempotency_key
                        and item.user_id == user_id
                        and _tenant_scope_matches(item.tenant_id, tenant_id)
                    ),
                    None,
                )
                if existing is not None:
                    existing_hash_matches = existing.payload_hash == payload_hash or (
                        existing.tenant_id is None
                        and tenant_id in {None, "default"}
                        and existing.payload_hash == legacy_payload_hash
                    )
                    if not existing_hash_matches:
                        raise ServiceError(
                            409,
                            4090001,
                            "idempotency key conflicts with a different poster task payload",
                        )
                    return PosterTaskCreateResponseData(
                        task_id=existing.task_id,
                        status=existing.accepted_status,
                        estimated_seconds=existing.estimated_seconds,
                    )
            created_at = now_iso()
            task = PosterTaskRecord(
                task_id=f"poster_{uuid4().hex[:12]}",
                user_id=user_id,
                tenant_id=tenant_id,
                campaign_id=campaign.campaign_id,
                campaign_name=campaign.name,
                theme=payload.theme,
                slogan=payload.slogan,
                size=payload.size,
                status="queued",
                created_at=created_at,
                estimated_seconds=estimated_seconds,
                updated_at=created_at,
            )
            self._snapshot.poster_tasks.append(task)
            if idempotency_key:
                self._snapshot.poster_idempotency_records.append(
                    PosterIdempotencyRecord(
                        key=idempotency_key,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        payload_hash=payload_hash,
                        task_id=task.task_id,
                        accepted_status="queued",
                        estimated_seconds=estimated_seconds,
                        created_at=created_at,
                    )
                )
            self._persist()
            return PosterTaskCreateResponseData(
                task_id=task.task_id,
                status="queued",
                estimated_seconds=estimated_seconds,
            )

    def get_poster_task(self, *, user_id: str, tenant_id: str | None, task_id: str):
        with self._lock:
            task = next(
                (
                    item
                    for item in self._snapshot.poster_tasks
                    if item.user_id == user_id
                    and _tenant_scope_matches(item.tenant_id, tenant_id)
                    and item.task_id == task_id
                ),
                None,
            )
            if task is None:
                return None
            changed = self._maybe_complete_poster(task)
            if changed:
                self._persist()
            return task.to_public()

    def list_poster_tasks(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        status: str | None,
        campaign_id: str | None,
    ) -> PosterTaskListData:
        with self._lock:
            tasks = [
                item
                for item in self._snapshot.poster_tasks
                if item.user_id == user_id and _tenant_scope_matches(item.tenant_id, tenant_id)
            ]
            changed = False
            for task in tasks:
                changed = self._maybe_complete_poster(task) or changed
            if changed:
                self._persist()
            if status:
                tasks = [item for item in tasks if item.status == status]
            if campaign_id:
                tasks = [item for item in tasks if item.campaign_id == campaign_id]
            reverse = sort_order != "asc"
            sort_field = sort_by if sort_by in {"created_at", "updated_at", "status", "theme"} else "updated_at"
            tasks.sort(key=lambda item: getattr(item, sort_field) or "", reverse=reverse)
            total = len(tasks)
            start = (page - 1) * page_size
            end = start + page_size
            items = [item.to_public() for item in tasks[start:end]]
            total_pages = (total + page_size - 1) // page_size if total else 0
            return PosterTaskListData(
                items=items,
                page=page,
                page_size=page_size,
                total=total,
                total_pages=total_pages,
                sort_by=sort_field,
                sort_order="desc" if reverse else "asc",
            )

    def _maybe_complete_poster(self, task: PosterTaskRecord) -> bool:
        if task.status not in {"queued", "running"}:
            return False
        settings = get_settings()
        created_at = datetime.fromisoformat(task.created_at)
        elapsed_seconds = max(int((utc_now() - created_at).total_seconds()), 0)
        auto_complete_seconds = max(settings.task_auto_complete_seconds, 0)
        if auto_complete_seconds > 0 and elapsed_seconds < auto_complete_seconds:
            if task.status != "running":
                task.status = "running"
                task.updated_at = now_iso()
                return True
            return False
        task.status = "completed"
        task.image_url = f"https://cdn.smartcloud.local/posters/{task.task_id}.png"
        task.updated_at = now_iso()
        return True

    def _get_user_visible_campaign(self, campaign_id: str) -> MarketingCampaignRecord | None:
        current_time = utc_now()
        return next(
            (
                item
                for item in self._snapshot.campaigns
                if item.campaign_id == campaign_id
                and self._is_user_visible_campaign(item, current_time=current_time)
            ),
            None,
        )

    def _is_user_visible_campaign(
        self,
        campaign: MarketingCampaignRecord,
        *,
        current_time: datetime | None = None,
    ) -> bool:
        if campaign.status != "published":
            return False
        now = current_time or utc_now()
        try:
            return datetime.fromisoformat(campaign.start_at) <= now <= datetime.fromisoformat(campaign.end_at)
        except ValueError:
            return False


@lru_cache(maxsize=1)
def get_marketing_store() -> MarketingStore:
    return MarketingStore(get_settings().data_path)


def _tenant_scope_matches(record_tenant_id: str | None, request_tenant_id: str | None) -> bool:
    return record_tenant_id == request_tenant_id or (
        record_tenant_id is None and request_tenant_id in {None, "default"}
    )


def _payload_hash(*, user_id: str, tenant_id: str | None, normalized_payload: str) -> str:
    return hashlib.sha256(f"{tenant_id or ''}:{user_id}:{normalized_payload}".encode("utf-8")).hexdigest()


def _legacy_payload_hash(*, user_id: str, normalized_payload: str) -> str:
    return hashlib.sha256(f"{user_id}:{normalized_payload}".encode("utf-8")).hexdigest()
