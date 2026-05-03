from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint, create_engine, delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

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


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "auth_users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    mobile: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    locale: Mapped[str] = mapped_column(String(32))
    time_zone: Mapped[str] = mapped_column(String(64))
    roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AdminRow(Base):
    __tablename__ = "auth_admins"

    admin_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(128))
    roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    menus: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    token_version: Mapped[int] = mapped_column(Integer, default=1)


class VerificationCodeRow(Base):
    __tablename__ = "auth_verification_codes"
    __table_args__ = (UniqueConstraint("scene", "account", "account_type", name="uq_auth_verification_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene: Mapped[str] = mapped_column(String(64), index=True)
    account: Mapped[str] = mapped_column(String(255), index=True)
    account_type: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PasswordChallengeRow(Base):
    __tablename__ = "auth_password_challenges"

    challenge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account: Mapped[str] = mapped_column(String(255), index=True)
    account_type: Mapped[str] = mapped_column(String(32), index=True)
    verification_code: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RefreshSessionRow(Base):
    __tablename__ = "auth_refresh_sessions"

    token_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class RevokedAccessTokenRow(Base):
    __tablename__ = "auth_revoked_access_tokens"

    token_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AdminConfirmationRow(Base):
    __tablename__ = "auth_admin_confirmations"

    confirm_token: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(255))
    resource_scope: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class InvalidationEventRow(Base):
    __tablename__ = "auth_invalidation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


def _connect_args(database_url: str) -> dict[str, Any]:
    return {"check_same_thread": False} if database_url.startswith("sqlite") else {}


def _normalize_database_url(value: str) -> str:
    if value.startswith("sqlite://"):
        return value
    if value.startswith("mysql://"):
        return value.replace("mysql://", "mysql+pymysql://", 1)
    return value


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return _coerce_utc(parsed)


def _serialize_datetime(value: datetime) -> str:
    return _coerce_utc(value).isoformat()


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_account_identifier(account: str, account_type: str | None = None) -> str:
    normalized = account.strip()
    normalized_type = account_type or ("email" if "@" in normalized else "mobile")
    if normalized_type == "email":
        return normalized.lower()
    return normalized


def _default_admin_menus() -> list[AdminMenuItem]:
    return [
        AdminMenuItem(code="dashboard", name="运营总览", path="/dashboard"),
        AdminMenuItem(code="knowledge", name="知识库管理", path="/knowledge"),
        AdminMenuItem(code="documents", name="文档索引", path="/documents"),
        AdminMenuItem(code="retrieval", name="检索诊断", path="/retrieval"),
        AdminMenuItem(code="agents", name="Agent 编排", path="/agents"),
        AdminMenuItem(code="marketing", name="营销活动", path="/marketing"),
        AdminMenuItem(code="audit", name="审计运行时", path="/audit"),
    ]


class AuthStore:
    def __init__(self, settings) -> None:
        self._settings = settings
        self._lock = RLock()
        self._database_url = _normalize_database_url(settings.database_url)
        self._engine = create_engine(self._database_url, future=True, connect_args=_connect_args(self._database_url))
        self._session_factory = sessionmaker(bind=self._engine, future=True, expire_on_commit=False)
        Base.metadata.create_all(self._engine)
        self._snapshot = AuthStoreSnapshot()
        self._last_prune_monotonic = 0.0
        self._bootstrap_path = settings.bootstrap_path
        self._ensure_seed_data()
        self._reload_snapshot()

    def _session(self):
        return self._session_factory()

    def clear(self) -> None:
        with self._lock:
            with self._session() as session:
                with session.begin():
                    for table in (
                        InvalidationEventRow,
                        AdminConfirmationRow,
                        RevokedAccessTokenRow,
                        RefreshSessionRow,
                        PasswordChallengeRow,
                        VerificationCodeRow,
                        AdminRow,
                        UserRow,
                    ):
                        session.execute(delete(table))
            self._ensure_seed_data()
            self._reload_snapshot()
            self._last_prune_monotonic = 0.0

    def ensure_acceptance_admin_account(self) -> None:
        self._ensure_seed_data()
        self._reload_snapshot()

    def _ensure_seed_data(self) -> None:
        settings = self._settings
        seed_email = settings.seed_user_email
        seed_mobile = settings.seed_user_mobile
        seed_password = settings.seed_user_password
        if not seed_email and not seed_mobile:
            return
        seed_user_id = "u_10001"
        with self._lock:
            with self._session() as session:
                with session.begin():
                    if session.get(UserRow, seed_user_id) is None:
                        session.add(
                            UserRow(
                                user_id=seed_user_id,
                                tenant_id="default",
                                name="演示用户",
                                email=normalize_account_identifier(seed_email, "email") if seed_email else None,
                                mobile=seed_mobile or None,
                                password_hash=_hash_password(seed_password) if seed_password else _hash_password(""),
                                avatar_url=None,
                                locale=settings.default_locale,
                                time_zone=settings.default_time_zone,
                                roles=["user"],
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
                                token_version=1,
                                account_id="acct-1001",
                            )
                        )
                    else:
                        demo_user = session.get(UserRow, seed_user_id)
                        if demo_user is not None:
                            if seed_email:
                                demo_user.email = normalize_account_identifier(seed_email, "email")
                            if seed_mobile:
                                demo_user.mobile = seed_mobile
                            if seed_password:
                                demo_user.password_hash = _hash_password(seed_password)
                            demo_user.permissions = [
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
                            ]
                            demo_user.account_id = "acct-1001"
                    seed_admin_username = settings.seed_admin_username
                    seed_admin_password = settings.seed_admin_password
                    if seed_admin_username and seed_admin_password:
                        if session.get(AdminRow, "admin_10001") is None:
                            session.add(
                                AdminRow(
                                    admin_id="admin_10001",
                                    username=seed_admin_username,
                                    name="系统管理员",
                                    password_hash=_hash_password(seed_admin_password),
                                    roles=["admin"],
                                    permissions=[
                                        "admin:manage",
                                        "user:manage",
                                        "admin:ops.read",
                                        "admin:ops.write",
                                        "admin:kb.read",
                                        "admin:kb.write",
                                        "admin:job.read",
                                        "admin:marketing.read",
                                        "admin:marketing.write",
                                    ],
                                    menus=[item.model_dump(mode="json") for item in _default_admin_menus()],
                                    token_version=1,
                                )
                            )
                        else:
                            admin_user = session.get(AdminRow, "admin_10001")
                            if admin_user is not None:
                                admin_user.username = seed_admin_username
                                admin_user.name = "系统管理员"
                                admin_user.password_hash = _hash_password(seed_admin_password)
                                admin_user.roles = ["admin"]
                                admin_user.permissions = [
                                    "admin:manage",
                                    "user:manage",
                                    "admin:ops.read",
                                    "admin:ops.write",
                                    "admin:kb.read",
                                    "admin:kb.write",
                                    "admin:job.read",
                                    "admin:marketing.read",
                                    "admin:marketing.write",
                                ]
                                admin_user.menus = [item.model_dump(mode="json") for item in _default_admin_menus()]

    def _reload_snapshot(self) -> None:
        with self._session() as session:
            users = [
                StoredUser(
                    user_id=row.user_id,
                    tenant_id=row.tenant_id,
                    name=row.name,
                    email=row.email,
                    mobile=row.mobile,
                    password_hash=row.password_hash,
                    avatar_url=row.avatar_url,
                    locale=row.locale,
                    time_zone=row.time_zone,
                    roles=list(row.roles or []),
                    permissions=list(row.permissions or []),
                    token_version=row.token_version,
                    account_id=row.account_id,
                )
                for row in session.scalars(select(UserRow).order_by(UserRow.user_id)).all()
            ]
            admins = [
                StoredAdmin(
                    admin_id=row.admin_id,
                    username=row.username,
                    name=row.name,
                    password_hash=row.password_hash,
                    roles=list(row.roles or []),
                    permissions=list(row.permissions or []),
                    menus=[AdminMenuItem.model_validate(item) for item in (row.menus or [])],
                    token_version=row.token_version,
                )
                for row in session.scalars(select(AdminRow).order_by(AdminRow.admin_id)).all()
            ]
            verification_codes = [
                StoredVerificationCode(
                    scene=row.scene,
                    account=row.account,
                    account_type=row.account_type,
                    code=row.code,
                    created_at=_serialize_datetime(row.created_at),
                    expires_at=_serialize_datetime(row.expires_at),
                )
                for row in session.scalars(select(VerificationCodeRow).order_by(VerificationCodeRow.id)).all()
            ]
            password_challenges = [
                StoredPasswordChallenge(
                    challenge_id=row.challenge_id,
                    account=row.account,
                    account_type=row.account_type,
                    verification_code=row.verification_code,
                    created_at=_serialize_datetime(row.created_at),
                    expires_at=_serialize_datetime(row.expires_at),
                )
                for row in session.scalars(select(PasswordChallengeRow).order_by(PasswordChallengeRow.challenge_id)).all()
            ]
            refresh_sessions = [
                StoredRefreshSession(
                    token_id=row.token_id,
                    subject_type=row.subject_type,
                    subject_id=row.subject_id,
                    token_version=row.token_version,
                    expires_at=_serialize_datetime(row.expires_at),
                    revoked=row.revoked,
                )
                for row in session.scalars(select(RefreshSessionRow).order_by(RefreshSessionRow.token_id)).all()
            ]
            revoked_access_tokens = [
                StoredRevokedAccessToken(
                    token_id=row.token_id,
                    subject_type=row.subject_type,
                    subject_id=row.subject_id,
                    expires_at=_serialize_datetime(row.expires_at),
                    revoked_at=_serialize_datetime(row.revoked_at),
                )
                for row in session.scalars(select(RevokedAccessTokenRow).order_by(RevokedAccessTokenRow.token_id)).all()
            ]
            admin_confirmations = [
                StoredAdminConfirmation(
                    confirm_token=row.confirm_token,
                    admin_id=row.admin_id,
                    action=row.action,
                    resource_scope=row.resource_scope,
                    created_at=_serialize_datetime(row.created_at),
                    expired_at=_serialize_datetime(row.expired_at),
                )
                for row in session.scalars(select(AdminConfirmationRow).order_by(AdminConfirmationRow.confirm_token)).all()
            ]
            invalidation_log = [
                StoredInvalidationEvent(
                    subject_type=row.subject_type,
                    subject_ids=list(row.subject_ids or []),
                    created_at=_serialize_datetime(row.created_at),
                )
                for row in session.scalars(select(InvalidationEventRow).order_by(InvalidationEventRow.id)).all()
            ]
        self._snapshot = AuthStoreSnapshot(
            users=users,
            admins=admins,
            verification_codes=verification_codes,
            password_challenges=password_challenges,
            refresh_sessions=refresh_sessions,
            revoked_access_tokens=revoked_access_tokens,
            admin_confirmations=admin_confirmations,
            invalidation_log=invalidation_log,
        )

    def _persist(self) -> None:
        with self._lock:
            with self._session() as session:
                with session.begin():
                    for item in self._snapshot.verification_codes:
                        row = session.scalar(
                            select(VerificationCodeRow).where(
                                VerificationCodeRow.scene == item.scene,
                                VerificationCodeRow.account == item.account,
                                VerificationCodeRow.account_type == item.account_type,
                            )
                        )
                        if row is not None:
                            row.code = item.code
                            row.created_at = _parse_iso(item.created_at)
                            row.expires_at = _parse_iso(item.expires_at)
                    for item in self._snapshot.refresh_sessions:
                        row = session.get(RefreshSessionRow, item.token_id)
                        if row is not None:
                            row.subject_type = item.subject_type
                            row.subject_id = item.subject_id
                            row.token_version = item.token_version
                            row.expires_at = _parse_iso(item.expires_at)
                            row.revoked = item.revoked
            self._reload_snapshot()

    def _prune_expired(self) -> None:
        now = datetime.now(UTC)
        if monotonic() - self._last_prune_monotonic < max(self._settings.prune_interval_seconds, 0):
            return
        try:
            with self._session() as session:
                with session.begin():
                    session.execute(delete(VerificationCodeRow).where(VerificationCodeRow.expires_at <= now))
                    session.execute(delete(PasswordChallengeRow).where(PasswordChallengeRow.expires_at <= now))
                    session.execute(delete(RefreshSessionRow).where(RefreshSessionRow.expires_at <= now))
                    session.execute(delete(RevokedAccessTokenRow).where(RevokedAccessTokenRow.expires_at <= now))
                    session.execute(delete(AdminConfirmationRow).where(AdminConfirmationRow.expired_at <= now))
        except OperationalError:
            try:
                self._engine.dispose()
            except Exception:
                pass
        finally:
            self._last_prune_monotonic = monotonic()
            try:
                self._reload_snapshot()
            except AttributeError:
                pass

    def get_user_by_account(self, account: str) -> StoredUser | None:
        self._prune_expired()
        normalized = normalize_account_identifier(account)
        with self._session() as session:
            row = session.scalar(select(UserRow).where((UserRow.email == normalized) | (UserRow.mobile == normalized)))
            return self._row_to_user(row)

    def get_user_by_account_type(self, account: str, account_type: str) -> StoredUser | None:
        self._prune_expired()
        normalized = normalize_account_identifier(account, account_type)
        with self._session() as session:
            if account_type == "email":
                row = session.scalar(select(UserRow).where(UserRow.email == normalized))
            else:
                row = session.scalar(select(UserRow).where(UserRow.mobile == normalized))
            return self._row_to_user(row)

    def get_user_by_id(self, user_id: str) -> StoredUser | None:
        self._prune_expired()
        with self._session() as session:
            return self._row_to_user(session.get(UserRow, user_id))

    def get_admin_by_username(self, username: str) -> StoredAdmin | None:
        self._prune_expired()
        normalized = username.strip().lower()
        with self._session() as session:
            row = session.scalar(select(AdminRow).where(AdminRow.username == normalized))
            if row is None and normalized != username.strip():
                row = session.scalar(select(AdminRow).where(AdminRow.username == username.strip()))
            return self._row_to_admin(row)

    def get_admin_by_id(self, admin_id: str) -> StoredAdmin | None:
        self._prune_expired()
        with self._session() as session:
            return self._row_to_admin(session.get(AdminRow, admin_id))

    def verify_user_password(self, user: StoredUser, password: str) -> bool:
        return user.password_hash == _hash_password(password)

    def verify_admin_password(self, admin: StoredAdmin, password: str) -> bool:
        return admin.password_hash == _hash_password(password)

    def issue_verification_code(self, *, scene: str, account: str, account_type: str) -> StoredVerificationCode:
        self._prune_expired()
        normalized = normalize_account_identifier(account, account_type)
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._settings.verification_code_ttl_seconds)
        with self._session() as session:
            with session.begin():
                row = session.scalar(
                    select(VerificationCodeRow).where(
                        VerificationCodeRow.scene == scene,
                        VerificationCodeRow.account == normalized,
                        VerificationCodeRow.account_type == account_type,
                    )
                )
                if row is not None and _coerce_utc(row.expires_at) > now:
                    result = self._row_to_verification_code(row)
                else:
                    if row is None:
                        row = VerificationCodeRow(
                            scene=scene,
                            account=normalized,
                            account_type=account_type,
                            code=self._settings.verification_code_value,
                            created_at=now,
                            expires_at=expires_at,
                        )
                        session.add(row)
                    else:
                        row.code = self._settings.verification_code_value
                        row.created_at = now
                        row.expires_at = expires_at
                    result = self._row_to_verification_code(row)
        self._reload_snapshot()
        return result

    def consume_verification_code(self, *, scene: str, account: str, account_type: str, code: str) -> bool:
        self._prune_expired()
        normalized = normalize_account_identifier(account, account_type)
        now = datetime.now(UTC)
        with self._session() as session:
            with session.begin():
                row = session.scalar(
                    select(VerificationCodeRow).where(
                        VerificationCodeRow.scene == scene,
                        VerificationCodeRow.account == normalized,
                        VerificationCodeRow.account_type == account_type,
                    )
                )
                if row is None or _coerce_utc(row.expires_at) <= now or row.code != code:
                    return False
                session.delete(row)
        self._reload_snapshot()
        return True

    def create_password_challenge(self, *, account: str, account_type: str, verification_code: str) -> StoredPasswordChallenge:
        self._prune_expired()
        now = datetime.now(UTC)
        row = PasswordChallengeRow(
            challenge_id=f"challenge_{uuid4().hex}",
            account=normalize_account_identifier(account, account_type),
            account_type=account_type,
            verification_code=verification_code,
            created_at=now,
            expires_at=now + timedelta(seconds=self._settings.reset_challenge_ttl_seconds),
        )
        with self._session() as session:
            with session.begin():
                session.add(row)
        self._reload_snapshot()
        return self._row_to_password_challenge(row)

    def get_password_challenge(self, challenge_id: str) -> StoredPasswordChallenge | None:
        self._prune_expired()
        now = datetime.now(UTC)
        with self._session() as session:
            row = session.get(PasswordChallengeRow, challenge_id)
            if row is None or _coerce_utc(row.expires_at) <= now:
                return None
            return self._row_to_password_challenge(row)

    def consume_password_challenge(self, challenge_id: str) -> None:
        with self._session() as session:
            with session.begin():
                row = session.get(PasswordChallengeRow, challenge_id)
                if row is not None:
                    session.delete(row)
        self._reload_snapshot()

    def reset_user_password(self, *, account: str, account_type: str, new_password: str) -> StoredUser | None:
        normalized = normalize_account_identifier(account, account_type)
        with self._session() as session:
            with session.begin():
                if account_type == "email":
                    row = session.scalar(select(UserRow).where(UserRow.email == normalized))
                else:
                    row = session.scalar(select(UserRow).where(UserRow.mobile == normalized))
                if row is None:
                    return None
                row.password_hash = _hash_password(new_password)
                row.token_version += 1
        self._reload_snapshot()
        return self.get_user_by_account_type(normalized, account_type)

    def change_user_password(self, user_id: str, *, old_password: str, new_password: str) -> StoredUser | None:
        with self._session() as session:
            with session.begin():
                row = session.get(UserRow, user_id)
                if row is None or row.password_hash != _hash_password(old_password):
                    return None
                row.password_hash = _hash_password(new_password)
                row.token_version += 1
        self._reload_snapshot()
        return self.get_user_by_id(user_id)

    def save_refresh_session(self, *, token_id: str, subject_type: str, subject_id: str, token_version: int, expires_at: str) -> None:
        with self._session() as session:
            with session.begin():
                row = session.get(RefreshSessionRow, token_id)
                expires = _parse_iso(expires_at)
                if row is None:
                    row = RefreshSessionRow(
                        token_id=token_id,
                        subject_type=subject_type,
                        subject_id=subject_id,
                        token_version=token_version,
                        expires_at=expires,
                        revoked=False,
                    )
                    session.add(row)
                else:
                    row.subject_type = subject_type
                    row.subject_id = subject_id
                    row.token_version = token_version
                    row.expires_at = expires
                    row.revoked = False
        self._reload_snapshot()

    def get_refresh_session(self, token_id: str) -> StoredRefreshSession | None:
        self._prune_expired()
        now = datetime.now(UTC)
        with self._session() as session:
            row = session.get(RefreshSessionRow, token_id)
            if row is None or _coerce_utc(row.expires_at) <= now:
                return None
            return self._row_to_refresh_session(row)

    def revoke_refresh_session(self, token_id: str) -> None:
        with self._session() as session:
            with session.begin():
                row = session.get(RefreshSessionRow, token_id)
                if row is not None:
                    row.revoked = True
        self._reload_snapshot()

    def revoke_subject_refresh_sessions(self, subject_type: str, subject_id: str) -> None:
        with self._session() as session:
            with session.begin():
                for row in session.scalars(
                    select(RefreshSessionRow).where(
                        RefreshSessionRow.subject_type == subject_type,
                        RefreshSessionRow.subject_id == subject_id,
                    )
                ):
                    row.revoked = True
        self._reload_snapshot()

    def revoke_access_token(self, *, token_id: str, subject_type: str, subject_id: str, expires_at: str) -> None:
        with self._session() as session:
            with session.begin():
                row = session.get(RevokedAccessTokenRow, token_id)
                if row is None:
                    session.add(
                        RevokedAccessTokenRow(
                            token_id=token_id,
                            subject_type=subject_type,
                            subject_id=subject_id,
                            expires_at=_parse_iso(expires_at),
                            revoked_at=datetime.now(UTC),
                        )
                    )
        self._reload_snapshot()

    def is_access_token_revoked(self, *, token_id: str, subject_type: str, subject_id: str) -> bool:
        self._prune_expired()
        now = datetime.now(UTC)
        with self._session() as session:
            row = session.get(RevokedAccessTokenRow, token_id)
            if row is None or _coerce_utc(row.expires_at) <= now:
                return False
            return row.subject_type == subject_type and row.subject_id == subject_id

    def update_user_profile(
        self,
        user_id: str,
        *,
        name: str | object = UNSET,
        avatar_url: str | None | object = UNSET,
        locale: str | object = UNSET,
        time_zone: str | object = UNSET,
    ) -> StoredUser:
        with self._session() as session:
            with session.begin():
                row = session.get(UserRow, user_id)
                if row is None:
                    raise KeyError(user_id)
                if name is not UNSET:
                    row.name = str(name).strip()
                if avatar_url is not UNSET:
                    row.avatar_url = None if avatar_url is None else str(avatar_url).strip()
                if locale is not UNSET:
                    row.locale = str(locale).strip()
                if time_zone is not UNSET:
                    row.time_zone = str(time_zone).strip()
        self._reload_snapshot()
        user = self.get_user_by_id(user_id)
        if user is None:
            raise KeyError(user_id)
        return user

    def create_admin_confirmation(self, *, admin_id: str, action: str, resource_scope: str) -> StoredAdminConfirmation:
        now = datetime.now(UTC)
        row = AdminConfirmationRow(
            confirm_token=f"confirm_{uuid4().hex}",
            admin_id=admin_id,
            action=action,
            resource_scope=resource_scope,
            created_at=now,
            expired_at=now + timedelta(seconds=self._settings.admin_confirm_ttl_seconds),
        )
        with self._session() as session:
            with session.begin():
                session.add(row)
        self._reload_snapshot()
        return self._row_to_admin_confirmation(row)

    def record_cache_invalidation(self, *, subject_type: str, subject_ids: list[str]) -> None:
        row = InvalidationEventRow(subject_type=subject_type, subject_ids=subject_ids, created_at=datetime.now(UTC))
        with self._session() as session:
            with session.begin():
                session.add(row)
        self._reload_snapshot()

    def _row_to_user(self, row: UserRow | None) -> StoredUser | None:
        if row is None:
            return None
        return StoredUser(
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            name=row.name,
            email=row.email,
            mobile=row.mobile,
            password_hash=row.password_hash,
            avatar_url=row.avatar_url,
            locale=row.locale,
            time_zone=row.time_zone,
            roles=list(row.roles or []),
            permissions=list(row.permissions or []),
            token_version=row.token_version,
            account_id=row.account_id,
        )

    def _row_to_admin(self, row: AdminRow | None) -> StoredAdmin | None:
        if row is None:
            return None
        return StoredAdmin(
            admin_id=row.admin_id,
            username=row.username,
            name=row.name,
            password_hash=row.password_hash,
            roles=list(row.roles or []),
            permissions=list(row.permissions or []),
            menus=[AdminMenuItem.model_validate(item) for item in (row.menus or [])],
            token_version=row.token_version,
        )

    def _row_to_verification_code(self, row: VerificationCodeRow) -> StoredVerificationCode:
        return StoredVerificationCode(
            scene=row.scene,
            account=row.account,
            account_type=row.account_type,
            code=row.code,
            created_at=_serialize_datetime(row.created_at),
            expires_at=_serialize_datetime(row.expires_at),
        )

    def _row_to_password_challenge(self, row: PasswordChallengeRow) -> StoredPasswordChallenge:
        return StoredPasswordChallenge(
            challenge_id=row.challenge_id,
            account=row.account,
            account_type=row.account_type,
            verification_code=row.verification_code,
            created_at=_serialize_datetime(row.created_at),
            expires_at=_serialize_datetime(row.expires_at),
        )

    def _row_to_refresh_session(self, row: RefreshSessionRow) -> StoredRefreshSession:
        return StoredRefreshSession(
            token_id=row.token_id,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            token_version=row.token_version,
            expires_at=_serialize_datetime(row.expires_at),
            revoked=row.revoked,
        )

    def _row_to_admin_confirmation(self, row: AdminConfirmationRow) -> StoredAdminConfirmation:
        return StoredAdminConfirmation(
            confirm_token=row.confirm_token,
            admin_id=row.admin_id,
            action=row.action,
            resource_scope=row.resource_scope,
            created_at=_serialize_datetime(row.created_at),
            expired_at=_serialize_datetime(row.expired_at),
        )


@lru_cache(maxsize=1)
def get_auth_store() -> AuthStore:
    return AuthStore(get_settings())
