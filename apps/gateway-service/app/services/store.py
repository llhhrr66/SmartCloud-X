from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class GatewayStore:
    def __init__(self, path: str, *, object_storage_base_url: str = "") -> None:
        self.path = Path(path)
        self._object_storage_base_url = object_storage_base_url.rstrip("/")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._state = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"users": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"users": {}}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _user_key(self, tenant_id: str | None, user_id: str) -> str:
        return f"{tenant_id or 'default'}:{user_id}"

    def _default_workspace(self) -> dict:
        created_at = now_iso()
        return {
            "orders": [],
            "refunds": [],
            "tickets": [],
            "ticket_replies": {},
            "icp_applications": [],
            "invoices": [],
            "pending_uploads": {},
            "files": {},
            "citations": {},
            "metadata": {"created_at": created_at, "updated_at": created_at},
        }

    def _workspace(self, tenant_id: str | None, user_id: str) -> dict:
        key = self._user_key(tenant_id, user_id)
        workspace = self._state["users"].get(key)
        if workspace is None:
            workspace = self._default_workspace()
            self._state["users"][key] = workspace
            self._save()
        return workspace

    def list_orders(self, tenant_id: str | None, user_id: str) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._workspace(tenant_id, user_id)["orders"])

    def list_refunds(self, tenant_id: str | None, user_id: str) -> list[dict]:
        with self._lock:
            refunds = copy.deepcopy(self._workspace(tenant_id, user_id)["refunds"])
            return sorted(refunds, key=lambda item: item["created_at"], reverse=True)

    def list_tickets(self, tenant_id: str | None, user_id: str) -> list[dict]:
        with self._lock:
            tickets = copy.deepcopy(self._workspace(tenant_id, user_id)["tickets"])
            return sorted(tickets, key=lambda item: item["updated_at"], reverse=True)

    def list_invoices(self, tenant_id: str | None, user_id: str) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._workspace(tenant_id, user_id)["invoices"])

    def workspace_updated_at(self, tenant_id: str | None, user_id: str) -> str:
        with self._lock:
            return str(self._workspace(tenant_id, user_id)["metadata"]["updated_at"])

    def order_detail(self, tenant_id: str | None, user_id: str, order_no: str) -> dict | None:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            order = next((item for item in workspace["orders"] if item["order_no"] == order_no), None)
            if order is None:
                return None
            refunds = [item for item in workspace["refunds"] if item["order_no"] == order_no]
            return {
                "order": copy.deepcopy(order),
                "instance_name": order.get("product_type") or order.get("instance_name", ""),
                "region": order.get("region", ""),
                "billing_mode": order.get("billing_mode", ""),
                "renew_type": order.get("renew_type", ""),
                "service_period": order.get("service_period") or order.get("billing_cycle", ""),
                "pay_time": order["created_at"],
                "configuration_summary": order.get("configuration_summary", []),
                "refunds": copy.deepcopy(refunds),
            }

    def upsert_order_snapshot(
        self,
        tenant_id: str | None,
        user_id: str,
        *,
        order_no: str,
        order_status: str,
        paid_amount: str,
        currency: str,
        refund_no: str | None,
        refund_status: str,
        invoice_status: str,
        product_type: str | None = None,
    ) -> dict:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            created_at = now_iso()
            existing = next((item for item in workspace["orders"] if item["order_no"] == order_no), None)
            record = {
                "order_no": order_no,
                "product_type": product_type or order_status,
                "status": order_status,
                "amount": paid_amount,
                "currency": currency,
                "created_at": existing.get("created_at", created_at) if existing else created_at,
                "eligible_for_refund": refund_status in {"not_requested", "processing"},
                "refund_no": refund_no,
                "refund_status": refund_status,
                "invoice_status": invoice_status,
            }
            if existing is None:
                workspace["orders"].insert(0, record)
            else:
                existing.update(record)
            workspace["metadata"]["updated_at"] = created_at
            self._save()
            return copy.deepcopy(record)

    def add_refund(
        self,
        tenant_id: str | None,
        user_id: str,
        *,
        order_no: str,
        refund_no: str,
        amount: str,
        status: str,
        reason: str,
        currency: str = "CNY",
    ) -> dict:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            created_at = now_iso()
            record = {
                "refund_no": refund_no,
                "order_no": order_no,
                "status": status,
                "requested_amount": amount,
                "currency": currency,
                "created_at": created_at,
                "timeline": [
                    {
                        "status": status,
                        "at": created_at,
                        "operator_type": "user",
                        "note": reason,
                    }
                ],
            }
            workspace["refunds"].insert(0, record)
            for order in workspace["orders"]:
                if order["order_no"] == order_no:
                    order["status"] = "refunding"
                    order["eligible_for_refund"] = False
            workspace["metadata"]["updated_at"] = created_at
            self._save()
            return copy.deepcopy(record)

    def ticket_detail(self, tenant_id: str | None, user_id: str, ticket_no: str) -> dict | None:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            ticket = next((item for item in workspace["tickets"] if item["ticket_no"] == ticket_no), None)
            if ticket is None:
                return None
            return {
                "ticket": copy.deepcopy(ticket),
                "replies": copy.deepcopy(workspace["ticket_replies"].get(ticket_no, [])),
            }

    def add_ticket(
        self,
        tenant_id: str | None,
        user_id: str,
        *,
        ticket_no: str,
        subject: str,
        content: str,
        category: str,
        priority: str,
        status: str,
        sla_minutes: int | None = None,
        attachments: list[dict] | None = None,
    ) -> dict:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            timestamp = now_iso()
            record = {
                "ticket_no": ticket_no,
                "subject": subject,
                "status": status,
                "category": category,
                "priority": priority,
                "content": content,
                "created_at": timestamp,
                "updated_at": timestamp,
                "sla_minutes": sla_minutes if sla_minutes is not None else 0,
                "attachments": attachments or [],
            }
            workspace["tickets"].insert(0, record)
            workspace["ticket_replies"][ticket_no] = []
            workspace["metadata"]["updated_at"] = timestamp
            self._save()
            return copy.deepcopy(record)

    def upsert_ticket_snapshot(
        self,
        tenant_id: str | None,
        user_id: str,
        *,
        ticket_no: str,
        subject: str,
        status: str,
        latest_action: str | None,
    ) -> dict:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            timestamp = now_iso()
            existing = next((item for item in workspace["tickets"] if item["ticket_no"] == ticket_no), None)
            record = {
                "ticket_no": ticket_no,
                "subject": subject,
                "status": status,
                "category": existing.get("category", "general") if existing else "general",
                "priority": existing.get("priority", "medium") if existing else "medium",
                "content": existing.get("content", latest_action or "") if existing else (latest_action or ""),
                "created_at": existing.get("created_at", timestamp) if existing else timestamp,
                "updated_at": timestamp,
                "sla_minutes": existing.get("sla_minutes", 0) if existing else 0,
                "attachments": existing.get("attachments", []) if existing else [],
            }
            if existing is None:
                workspace["tickets"].insert(0, record)
            else:
                existing.update(record)
            workspace["metadata"]["updated_at"] = timestamp
            self._save()
            return copy.deepcopy(record)

    def add_ticket_reply(
        self,
        tenant_id: str | None,
        user_id: str,
        *,
        ticket_no: str,
        reply_no: str,
        content: str,
        attachments: list[dict] | None = None,
    ) -> dict:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            timestamp = now_iso()
            reply = {
                "reply_no": reply_no,
                "content": content,
                "created_at": timestamp,
                "operator_type": "user",
                "attachments": attachments or [],
                "status": "sent",
            }
            workspace["ticket_replies"].setdefault(ticket_no, []).append(reply)
            for ticket in workspace["tickets"]:
                if ticket["ticket_no"] == ticket_no:
                    ticket["updated_at"] = timestamp
            workspace["metadata"]["updated_at"] = timestamp
            self._save()
            return copy.deepcopy(reply)

    def list_icp_applications(self, tenant_id: str | None, user_id: str) -> list[dict]:
        with self._lock:
            applications = copy.deepcopy(self._workspace(tenant_id, user_id)["icp_applications"])
            return sorted(
                applications,
                key=lambda item: item.get("submitted_at") or "",
                reverse=True,
            )

    def get_icp_application(self, tenant_id: str | None, user_id: str, application_no: str) -> dict | None:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            application = next(
                (
                    item
                    for item in workspace["icp_applications"]
                    if item["application_no"] == application_no
                ),
                None,
            )
            return copy.deepcopy(application) if application else None

    def add_icp_application(
        self,
        tenant_id: str | None,
        user_id: str,
        *,
        application_no: str,
        domain: str,
        website_name: str,
        subject_type: str,
        contacts: list[str],
        materials: list[dict],
        status: str,
        current_step: str,
    ) -> dict:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            timestamp = now_iso()
            record = {
                "application_no": application_no,
                "status": status,
                "current_step": current_step,
                "domain": domain,
                "website_name": website_name,
                "subject_type": subject_type,
                "contacts": contacts,
                "materials": materials,
                "submitted_at": timestamp,
            }
            workspace["icp_applications"].insert(0, record)
            workspace["metadata"]["updated_at"] = timestamp
            self._save()
            return copy.deepcopy(record)

    def upsert_icp_application_snapshot(
        self,
        tenant_id: str | None,
        user_id: str,
        *,
        application_no: str,
        status: str,
        current_step: str,
        latest_action: str | None,
        domain: str | None,
    ) -> dict:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            timestamp = now_iso()
            existing = next(
                (item for item in workspace["icp_applications"] if item["application_no"] == application_no),
                None,
            )
            record = {
                "application_no": application_no,
                "status": status,
                "current_step": current_step,
                "latest_action": latest_action,
                "domain": domain or (existing.get("domain") if existing else ""),
                "website_name": existing.get("website_name", "") if existing else "",
                "subject_type": existing.get("subject_type", "enterprise") if existing else "enterprise",
                "contacts": existing.get("contacts", []) if existing else [],
                "materials": existing.get("materials", []) if existing else [],
                "submitted_at": existing.get("submitted_at", timestamp) if existing else timestamp,
            }
            if existing is None:
                workspace["icp_applications"].insert(0, record)
            else:
                existing.update(record)
            workspace["metadata"]["updated_at"] = timestamp
            self._save()
            return copy.deepcopy(record)

    def create_upload_policy(
        self,
        tenant_id: str | None,
        user_id: str,
        *,
        file_name: str,
        size: int,
        mime_type: str,
        biz_type: str,
    ) -> dict:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            file_id = f"file_{uuid4().hex[:12]}"
            object_key = f"uploads/{tenant_id or 'default'}/{user_id}/{file_id}/{file_name}"
            expire_at = (datetime.now(UTC) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
            policy = {
                "file_id": file_id,
                "upload_url": f"{self._object_storage_base_url}/uploads/{file_id}",
                "form_fields": {},
                "object_key": object_key,
                "expire_at": expire_at,
            }
            workspace["pending_uploads"][file_id] = {
                "file_name": file_name,
                "size": size,
                "mime_type": mime_type,
                "biz_type": biz_type,
                "object_key": object_key,
                "expire_at": expire_at,
            }
            self._save()
            return copy.deepcopy(policy)

    def complete_upload(
        self,
        tenant_id: str | None,
        user_id: str,
        *,
        file_id: str,
        object_key: str,
        size: int,
    ) -> dict:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            pending = workspace["pending_uploads"].pop(file_id, {})
            record = {
                "file_id": file_id,
                "file_name": pending.get("file_name", Path(object_key).name),
                "size": size,
                "mime_type": pending.get("mime_type", "application/octet-stream"),
                "download_url": f"{self._object_storage_base_url}/downloads/{file_id}",
                "expires_at": pending.get("expire_at"),
                "status": "ready",
                "scan_status": "passed",
            }
            workspace["files"][file_id] = record
            workspace["metadata"]["updated_at"] = now_iso()
            self._save()
            return copy.deepcopy(record)

    def get_file(self, tenant_id: str | None, user_id: str, file_id: str) -> dict | None:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            if file_id in workspace["files"]:
                return copy.deepcopy(workspace["files"][file_id])
            if file_id.startswith("report-"):
                return {
                    "file_id": file_id,
                    "file_name": f"{file_id}.md",
                    "size": 0,
                    "mime_type": "text/markdown",
                    "download_url": f"{self._object_storage_base_url}/downloads/{file_id}",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    "status": "pending",
                    "scan_status": "pending",
                }
            return None

    def delete_file(self, tenant_id: str | None, user_id: str, file_id: str) -> bool:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            deleted = workspace["files"].pop(file_id, None) is not None
            if deleted:
                self._save()
            return deleted

    def remember_citations(self, tenant_id: str | None, user_id: str, citations: list[dict]) -> None:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            for citation in citations:
                citation_id = citation.get("citation_id") or citation.get("id")
                if citation_id:
                    workspace["citations"][citation_id] = citation
            self._save()

    def get_citation(self, tenant_id: str | None, user_id: str, citation_id: str) -> dict | None:
        with self._lock:
            workspace = self._workspace(tenant_id, user_id)
            citation = workspace["citations"].get(citation_id)
            return copy.deepcopy(citation) if citation else None
