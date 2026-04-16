from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.core.config import get_settings
from app.models import (
    AdminMenuItem,
    AuthStoreSnapshot,
    StoredAdmin,
    StoredAdminConfirmation,
    StoredInvalidationEvent,
    StoredPasswordChallenge,
    StoredRefreshSession,
    StoredRevokedAccessToken,
    StoredUser,
    StoredVerificationCode,
    now_iso,
)

UNSET = object()


class AuthStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._lock = RLock()
        self._snapshot = self._load()

    def _load(self) -> AuthStoreSnapshot:
        if self.file_path.exists():
            return AuthStoreSnapshot.model_validate_json(self.file_path.read_text(encoding="utf-8"))
        snapshot = self._default_snapshot()
        self._persist(snapshot)
        return snapshot

    def _persist(self, snapshot: AuthStoreSnapshot | None = None) -> None:
        with self._lock:
            target = snapshot or self._snapshot
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_path.write_text(target.model_dump_json(indent=2), encoding="utf-8")

    def _default_snapshot(self) -> AuthStoreSnapshot:
        settings = get_settings()
        return AuthStoreSnapshot(
            users=[
                StoredUser(
                    user_id="u_10001",
                    tenant_id="default",
                    name="SmartCloud 用户",
                    email="demo@smartcloud.local",
                    mobile="13800000001",
                    password_hash=_hash_password("Password123!"),
                    locale=settings.default_locale,
                    time_zone=settings.default_time_zone,
                    permissions=[
                        "user:chat.use",
                        "user:billing.read",
                        "user:order.read",
                        "user:ticket.read",
                        "user:ticket.write",
                        "user:icp.read",
                        "user:icp.write",
                        "user:marketing.read",
                        "user:marketing.write",
                        "user:research.read",
                        "user:research.write",
                    ],
                )
            ],
            admins=[
                StoredAdmin(
                    admin_id="admin_10001",
                    username="admin",
                    name="平台管理员",
                    password_hash=_hash_password("Admin123!"),
                    roles=["ops_admin"],
                    permissions=[
                        "admin:ops.read",
                        "admin:ops.write",
                        "admin:user.read",
                        "admin:user.write",
                        "admin:marketing.read",
                        "admin:marketing.write",
                        "admin:kb.read",
                        "admin:kb.write",
                        "admin:job.read",
                    ],
                    menus=_default_admin_menus(),
                )
            ],
        )

    def clear(self) -> None:
        with self._lock:
            self._snapshot = self._default_snapshot()
            self._persist()

    def _prune_expired(self) -> None:
        with self._lock:
            now = datetime.now(UTC)
            before_counts = (
                len(self._snapshot.verification_codes),
                len(self._snapshot.password_challenges),
                len(self._snapshot.refresh_sessions),
                len(self._snapshot.revoked_access_tokens),
                len(self._snapshot.admin_confirmations),
            )
            self._snapshot.verification_codes = [
                item
                for item in self._snapshot.verification_codes
                if _parse_datetime(item.expires_at) > now
            ]
            self._snapshot.password_challenges = [
                item
                for item in self._snapshot.password_challenges
                if _parse_datetime(item.expires_at) > now
            ]
            self._snapshot.refresh_sessions = [
                item
                for item in self._snapshot.refresh_sessions
                if _parse_datetime(item.expires_at) > now
            ]
            self._snapshot.revoked_access_tokens = [
                item
                for item in self._snapshot.revoked_access_tokens
                if _parse_datetime(item.expires_at) > now
            ]
            self._snapshot.admin_confirmations = [
                item
                for item in self._snapshot.admin_confirmations
                if _parse_datetime(item.expired_at) > now
            ]
            after_counts = (
                len(self._snapshot.verification_codes),
                len(self._snapshot.password_challenges),
                len(self._snapshot.refresh_sessions),
                len(self._snapshot.revoked_access_tokens),
                len(self._snapshot.admin_confirmations),
            )
            if after_counts != before_counts:
                self._persist()

    def get_user_by_id(self, user_id: str) -> StoredUser | None:
        with self._lock:
            self._prune_expired()
            return next((user for user in self._snapshot.users if user.user_id == user_id), None)

    def get_user_by_account(self, account: str) -> StoredUser | None:
        with self._lock:
            self._prune_expired()
            normalized_email = normalize_account_identifier(account, "email")
            normalized_mobile = normalize_account_identifier(account, "mobile")
            normalized_user_id = account.strip()
            return next(
                (
                    user
                    for user in self._snapshot.users
                    if user.email.lower() == normalized_email
                    or normalize_account_identifier(user.mobile, "mobile") == normalized_mobile
                    or user.user_id == normalized_user_id
                ),
                None,
            )

    def get_user_by_account_type(self, account: str, account_type: str) -> StoredUser | None:
        with self._lock:
            self._prune_expired()
            normalized = normalize_account_identifier(account, account_type)
            if account_type == "email":
                return next(
                    (user for user in self._snapshot.users if user.email.lower() == normalized),
                    None,
                )
            if account_type == "mobile":
                return next(
                    (
                        user
                        for user in self._snapshot.users
                        if normalize_account_identifier(user.mobile, "mobile") == normalized
                    ),
                    None,
                )
            return None

    def get_admin_by_id(self, admin_id: str) -> StoredAdmin | None:
        with self._lock:
            self._prune_expired()
            return next((admin for admin in self._snapshot.admins if admin.admin_id == admin_id), None)

    def get_admin_by_username(self, username: str) -> StoredAdmin | None:
        with self._lock:
            self._prune_expired()
            normalized = username.strip().lower()
            return next((admin for admin in self._snapshot.admins if admin.username.lower() == normalized), None)

    def verify_user_password(self, user: StoredUser, password: str) -> bool:
        return user.password_hash == _hash_password(password)

    def verify_admin_password(self, admin: StoredAdmin, password: str) -> bool:
        return admin.password_hash == _hash_password(password)

    def issue_verification_code(
        self,
        *,
        scene: str,
        account: str,
        account_type: str,
    ) -> StoredVerificationCode:
        with self._lock:
            self._prune_expired()
            normalized_account = normalize_account_identifier(account, account_type)
            existing = next(
                (
                    item
                    for item in self._snapshot.verification_codes
                    if item.scene == scene
                    and item.account == normalized_account
                    and item.account_type == account_type
                ),
                None,
            )
            if existing is not None:
                return existing
            created_at = now_iso()
            expires_at = (datetime.now(UTC) + timedelta(seconds=get_settings().verification_code_ttl_seconds)).isoformat()
            record = StoredVerificationCode(
                scene=scene,
                account=normalized_account,
                account_type=account_type,
                code="123456",
                created_at=created_at,
                expires_at=expires_at,
            )
            self._snapshot.verification_codes = [
                item
                for item in self._snapshot.verification_codes
                if not (
                    item.scene == record.scene
                    and item.account == record.account
                    and item.account_type == record.account_type
                )
            ]
            self._snapshot.verification_codes.append(record)
            self._persist()
            return record

    def verify_code(self, *, scene: str, account: str, account_type: str, code: str) -> bool:
        with self._lock:
            self._prune_expired()
            normalized_account = normalize_account_identifier(account, account_type)
            return any(
                item.scene == scene
                and item.account == normalized_account
                and item.account_type == account_type
                and item.code == code
                for item in self._snapshot.verification_codes
            )

    def consume_verification_code(self, *, scene: str, account: str, account_type: str, code: str) -> bool:
        with self._lock:
            self._prune_expired()
            normalized_account = normalize_account_identifier(account, account_type)
            for index, item in enumerate(self._snapshot.verification_codes):
                if (
                    item.scene == scene
                    and item.account == normalized_account
                    and item.account_type == account_type
                    and item.code == code
                ):
                    del self._snapshot.verification_codes[index]
                    self._persist()
                    return True
            return False

    def create_password_challenge(
        self,
        *,
        account: str,
        account_type: str,
        verification_code: str,
    ) -> StoredPasswordChallenge:
        with self._lock:
            self._prune_expired()
            normalized_account = normalize_account_identifier(account, account_type)
            created_at = now_iso()
            expires_at = (datetime.now(UTC) + timedelta(seconds=get_settings().reset_challenge_ttl_seconds)).isoformat()
            challenge = StoredPasswordChallenge(
                challenge_id=f"pwd_challenge_{uuid4().hex[:12]}",
                account=normalized_account,
                account_type=account_type,
                verification_code=verification_code,
                created_at=created_at,
                expires_at=expires_at,
            )
            self._snapshot.password_challenges = [
                item
                for item in self._snapshot.password_challenges
                if not (item.account == normalized_account and item.account_type == account_type)
            ]
            self._snapshot.password_challenges.append(challenge)
            self._persist()
            return challenge

    def get_password_challenge(self, challenge_id: str) -> StoredPasswordChallenge | None:
        with self._lock:
            self._prune_expired()
            return next(
                (
                    item
                    for item in self._snapshot.password_challenges
                    if item.challenge_id == challenge_id
                ),
                None,
            )

    def consume_password_challenge(self, challenge_id: str) -> None:
        with self._lock:
            self._snapshot.password_challenges = [
                item
                for item in self._snapshot.password_challenges
                if item.challenge_id != challenge_id
            ]
            self._persist()

    def save_refresh_session(
        self,
        *,
        token_id: str,
        subject_type: str,
        subject_id: str,
        token_version: int,
        expires_at: str,
    ) -> None:
        with self._lock:
            self._prune_expired()
            self._snapshot.refresh_sessions = [
                item for item in self._snapshot.refresh_sessions if item.token_id != token_id
            ]
            self._snapshot.refresh_sessions.append(
                StoredRefreshSession(
                    token_id=token_id,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    token_version=token_version,
                    expires_at=expires_at,
                    revoked=False,
                )
            )
            self._persist()

    def get_refresh_session(self, token_id: str) -> StoredRefreshSession | None:
        with self._lock:
            self._prune_expired()
            return next(
                (item for item in self._snapshot.refresh_sessions if item.token_id == token_id),
                None,
            )

    def revoke_refresh_session(self, token_id: str) -> None:
        with self._lock:
            for item in self._snapshot.refresh_sessions:
                if item.token_id == token_id:
                    item.revoked = True
            self._persist()

    def revoke_access_token(
        self,
        *,
        token_id: str,
        subject_type: str,
        subject_id: str,
        expires_at: str,
    ) -> None:
        if not token_id or not expires_at:
            return
        with self._lock:
            self._prune_expired()
            self._snapshot.revoked_access_tokens = [
                item for item in self._snapshot.revoked_access_tokens if item.token_id != token_id
            ]
            self._snapshot.revoked_access_tokens.append(
                StoredRevokedAccessToken(
                    token_id=token_id,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    expires_at=expires_at,
                    revoked_at=now_iso(),
                )
            )
            self._persist()

    def is_access_token_revoked(
        self,
        *,
        token_id: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
    ) -> bool:
        if not token_id:
            return False
        with self._lock:
            self._prune_expired()
            return any(
                item.token_id == token_id
                and (subject_type is None or item.subject_type == subject_type)
                and (subject_id is None or item.subject_id == subject_id)
                for item in self._snapshot.revoked_access_tokens
            )

    def revoke_subject_refresh_sessions(self, subject_type: str, subject_id: str) -> None:
        with self._lock:
            for item in self._snapshot.refresh_sessions:
                if item.subject_type == subject_type and item.subject_id == subject_id:
                    item.revoked = True
            self._persist()

    def update_user_profile(
        self,
        user_id: str,
        *,
        name: str | None | object = UNSET,
        avatar_url: str | None | object = UNSET,
        locale: str | None | object = UNSET,
        time_zone: str | None | object = UNSET,
    ) -> StoredUser:
        with self._lock:
            user = self.get_user_by_id(user_id)
            if user is None:
                raise KeyError(user_id)
            if name is not UNSET and name is not None:
                user.name = name
            if avatar_url is not UNSET:
                user.avatar_url = avatar_url
            if locale is not UNSET and locale is not None:
                user.locale = locale
            if time_zone is not UNSET and time_zone is not None:
                user.time_zone = time_zone
            self._persist()
            return user

    def change_user_password(self, user_id: str, *, old_password: str, new_password: str) -> StoredUser | None:
        with self._lock:
            user = self.get_user_by_id(user_id)
            if user is None:
                return None
            if user.password_hash != _hash_password(old_password):
                return None
            user.password_hash = _hash_password(new_password)
            user.token_version += 1
            self._persist()
            return user

    def reset_user_password(self, *, account: str, account_type: str, new_password: str) -> StoredUser | None:
        with self._lock:
            user = self.get_user_by_account_type(account, account_type)
            if user is None:
                return None
            user.password_hash = _hash_password(new_password)
            user.token_version += 1
            self._persist()
            return user

    def create_admin_confirmation(self, *, admin_id: str, action: str, resource_scope: str) -> StoredAdminConfirmation:
        with self._lock:
            created_at = now_iso()
            expired_at = (datetime.now(UTC) + timedelta(seconds=get_settings().admin_confirm_ttl_seconds)).isoformat()
            record = StoredAdminConfirmation(
                confirm_token=f"confirm_{uuid4().hex[:16]}",
                admin_id=admin_id,
                action=action,
                resource_scope=resource_scope,
                created_at=created_at,
                expired_at=expired_at,
            )
            self._snapshot.admin_confirmations.append(record)
            self._persist()
            return record

    def record_cache_invalidation(self, *, subject_type: str, subject_ids: list[str]) -> None:
        with self._lock:
            self._snapshot.invalidation_log.append(
                StoredInvalidationEvent(
                    subject_type=subject_type,
                    subject_ids=subject_ids,
                    created_at=now_iso(),
                )
            )
            self._persist()


def _default_admin_menus() -> list[AdminMenuItem]:
    return [
        AdminMenuItem(code="dashboard", name="控制台", path="/dashboard", icon="dashboard"),
        AdminMenuItem(code="users", name="用户管理", path="/users", icon="users"),
        AdminMenuItem(code="marketing", name="营销中心", path="/marketing", icon="megaphone"),
        AdminMenuItem(code="knowledge", name="知识库", path="/knowledge", icon="book"),
    ]


def _hash_password(raw_password: str) -> str:
    return hashlib.sha256(f"smartcloud-x::{raw_password}".encode("utf-8")).hexdigest()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


@lru_cache(maxsize=1)
def get_auth_store() -> AuthStore:
    return AuthStore(get_settings().data_path)


def normalize_account_identifier(account: str, account_type: str | None = None) -> str:
    normalized = account.strip()
    if account_type == "email" or (account_type is None and "@" in normalized):
        return normalized.lower()
    return normalized
