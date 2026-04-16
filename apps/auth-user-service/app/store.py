from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint, create_engine, delete, select
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
    mobile: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    locale: Mapped[str] = mapped_column(String(32))
    time_zone: Mapped[str] = mapped_column(String(64))
    roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    token_version: Mapped[int] = mapped_column(Integer, default=1)


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
    __table_args__ = (
        UniqueConstraint("scene", "account", "account_type", name="uq_auth_verification_code_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene: Mapped[str] = mapped_column(String(64), index=True)
    account: Mapped[str] = mapped_column(String(255), index=True)
    account_type: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PasswordChallengeRow(Base):
    __tablename__ = "auth_password_challenges"

    challenge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account: Mapped[str] = mapped_column(String(255), index=True)
    account_type: Mapped[str] = mapped_column(String(32))
    verification_code: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RefreshSessionRow(Base):
    __tablename__ = "auth_refresh_sessions"

    token_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    token_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class RevokedAccessTokenRow(Base):
    __tablename__ = "auth_revoked_access_tokens"

    token_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AdminConfirmationRow(Base):
    __tablename__ = "auth_admin_confirmations"

    confirm_token: Mapped[str] = mapped_column(String(128), primary_key=True)
    admin_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(255))
    resource_scope: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class InvalidationEventRow(Base):
    __tablename__ = "auth_invalidation_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._lock = RLock()
        self._engine = create_engine(
            _normalize_database_url(self.settings.database_url),
            future=True,
            connect_args=_connect_args(self.settings.database_url),
            json_serializer=lambda value: json.dumps(value, ensure_ascii=False),
            pool_pre_ping=True,
        )
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False, future=True)
        Base.metadata.create_all(self._engine)
        self._bootstrap_if_needed()
        self._snapshot = self._load_snapshot()

    def _session(self) -> Session:
        return self._session_factory()

    def _bootstrap_if_needed(self) -> None:
        with self._session() as session:
            total_rows = sum(
                session.execute(select(model).limit(1)).first() is not None
                for model in (UserRow, AdminRow, VerificationCodeRow, PasswordChallengeRow, RefreshSessionRow)
            )
        if total_rows:
            return
        snapshot = self._load_bootstrap_snapshot()
        self._replace_snapshot(snapshot)
        self._prune_expired()

    def _load_bootstrap_snapshot(self) -> AuthStoreSnapshot:
        bootstrap_path = self.settings.bootstrap_path
        if bootstrap_path and bootstrap_path.exists():
            return AuthStoreSnapshot.model_validate_json(bootstrap_path.read_text(encoding="utf-8"))
        return self._default_snapshot()

    def _load_snapshot(self) -> AuthStoreSnapshot:
        with self._session() as session:
            users = [self._row_to_user(item) for item in session.scalars(select(UserRow).order_by(UserRow.user_id)).all()]
            admins = [self._row_to_admin(item) for item in session.scalars(select(AdminRow).order_by(AdminRow.admin_id)).all()]
            verification_codes = [
                self._row_to_verification_code(item)
                for item in session.scalars(
                    select(VerificationCodeRow).order_by(VerificationCodeRow.created_at, VerificationCodeRow.id)
                ).all()
            ]
            password_challenges = [
                self._row_to_password_challenge(item)
                for item in session.scalars(
                    select(PasswordChallengeRow).order_by(PasswordChallengeRow.created_at)
                ).all()
            ]
            refresh_sessions = [
                self._row_to_refresh_session(item)
                for item in session.scalars(select(RefreshSessionRow).order_by(RefreshSessionRow.expires_at)).all()
            ]
            revoked_access_tokens = [
                self._row_to_revoked_access_token(item)
                for item in session.scalars(
                    select(RevokedAccessTokenRow).order_by(RevokedAccessTokenRow.revoked_at)
                ).all()
            ]
            admin_confirmations = [
                self._row_to_admin_confirmation(item)
                for item in session.scalars(
                    select(AdminConfirmationRow).order_by(AdminConfirmationRow.created_at)
                ).all()
            ]
            invalidation_log = [
                self._row_to_invalidation_event(item)
                for item in session.scalars(
                    select(InvalidationEventRow).order_by(InvalidationEventRow.created_at, InvalidationEventRow.id)
                ).all()
            ]
        return AuthStoreSnapshot(
            users=users,
            admins=admins,
            verification_codes=verification_codes,
            password_challenges=password_challenges,
            refresh_sessions=refresh_sessions,
            revoked_access_tokens=revoked_access_tokens,
            admin_confirmations=admin_confirmations,
            invalidation_log=invalidation_log,
        )

    def _replace_snapshot(self, snapshot: AuthStoreSnapshot) -> None:
        with self._lock:
            with self._session() as session:
                with session.begin():
                    for model in (
                        InvalidationEventRow,
                        AdminConfirmationRow,
                        RevokedAccessTokenRow,
                        RefreshSessionRow,
                        PasswordChallengeRow,
                        VerificationCodeRow,
                        AdminRow,
                        UserRow,
                    ):
                        session.execute(delete(model))
                    session.add_all([
                        UserRow(
                            user_id=item.user_id,
                            tenant_id=item.tenant_id,
                            name=item.name,
                            email=item.email,
                            mobile=item.mobile,
                            password_hash=item.password_hash,
                            avatar_url=item.avatar_url,
                            locale=item.locale,
                            time_zone=item.time_zone,
                            roles=list(item.roles),
                            permissions=list(item.permissions),
                            token_version=item.token_version,
                        )
                        for item in snapshot.users
                    ])
                    session.add_all([
                        AdminRow(
                            admin_id=item.admin_id,
                            username=item.username,
                            name=item.name,
                            password_hash=item.password_hash,
                            roles=list(item.roles),
                            permissions=list(item.permissions),
                            menus=[menu.model_dump(mode="json") for menu in item.menus],
                            token_version=item.token_version,
                        )
                        for item in snapshot.admins
                    ])
                    session.add_all([
                        VerificationCodeRow(
                            scene=item.scene,
                            account=item.account,
                            account_type=item.account_type,
                            code=item.code,
                            created_at=_parse_datetime(item.created_at),
                            expires_at=_parse_datetime(item.expires_at),
                        )
                        for item in snapshot.verification_codes
                    ])
                    session.add_all([
                        PasswordChallengeRow(
                            challenge_id=item.challenge_id,
                            account=item.account,
                            account_type=item.account_type,
                            verification_code=item.verification_code,
                            created_at=_parse_datetime(item.created_at),
                            expires_at=_parse_datetime(item.expires_at),
                        )
                        for item in snapshot.password_challenges
                    ])
                    session.add_all([
                        RefreshSessionRow(
                            token_id=item.token_id,
                            subject_type=item.subject_type,
                            subject_id=item.subject_id,
                            token_version=item.token_version,
                            expires_at=_parse_datetime(item.expires_at),
                            revoked=item.revoked,
                        )
                        for item in snapshot.refresh_sessions
                    ])
                    session.add_all([
                        RevokedAccessTokenRow(
                            token_id=item.token_id,
                            subject_type=item.subject_type,
                            subject_id=item.subject_id,
                            expires_at=_parse_datetime(item.expires_at),
                            revoked_at=_parse_datetime(item.revoked_at),
                        )
                        for item in snapshot.revoked_access_tokens
                    ])
                    session.add_all([
                        AdminConfirmationRow(
                            confirm_token=item.confirm_token,
                            admin_id=item.admin_id,
                            action=item.action,
                            resource_scope=item.resource_scope,
                            created_at=_parse_datetime(item.created_at),
                            expired_at=_parse_datetime(item.expired_at),
                        )
                        for item in snapshot.admin_confirmations
                    ])
                    session.add_all([
                        InvalidationEventRow(
                            subject_type=item.subject_type,
                            subject_ids=list(item.subject_ids),
                            created_at=_parse_datetime(item.created_at),
                        )
                        for item in snapshot.invalidation_log
                    ])
        self._snapshot = self._load_snapshot()

    def _persist(self, snapshot: AuthStoreSnapshot | None = None) -> None:
        self._replace_snapshot(snapshot or self._snapshot)

    def _default_snapshot(self) -> AuthStoreSnapshot:
        return AuthStoreSnapshot(
            users=[
                StoredUser(
                    user_id="u_10001",
                    tenant_id="default",
                    name="SmartCloud 用户",
                    email="demo@smartcloud.local",
                    mobile="13800000001",
                    password_hash=_hash_password("Password123!"),
                    locale=self.settings.default_locale,
                    time_zone=self.settings.default_time_zone,
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
            Base.metadata.drop_all(self._engine)
            Base.metadata.create_all(self._engine)
            self._replace_snapshot(self._default_snapshot())

    def _prune_expired(self) -> None:
        now = datetime.now(UTC)
        with self._session() as session:
            with session.begin():
                session.execute(delete(VerificationCodeRow).where(VerificationCodeRow.expires_at <= now))
                session.execute(delete(PasswordChallengeRow).where(PasswordChallengeRow.expires_at <= now))
                session.execute(delete(RefreshSessionRow).where(RefreshSessionRow.expires_at <= now))
                session.execute(delete(RevokedAccessTokenRow).where(RevokedAccessTokenRow.expires_at <= now))
                session.execute(delete(AdminConfirmationRow).where(AdminConfirmationRow.expired_at <= now))
        self._snapshot = self._load_snapshot()

    def get_user_by_id(self, user_id: str) -> StoredUser | None:
        self._prune_expired()
        with self._session() as session:
            row = session.get(UserRow, user_id)
            return self._row_to_user(row) if row else None

    def get_user_by_account(self, account: str) -> StoredUser | None:
        self._prune_expired()
        normalized_email = normalize_account_identifier(account, "email")
        normalized_mobile = normalize_account_identifier(account, "mobile")
        normalized_user_id = account.strip()
        with self._session() as session:
            row = session.scalars(
                select(UserRow).where(
                    (UserRow.email == normalized_email)
                    | (UserRow.mobile == normalized_mobile)
                    | (UserRow.user_id == normalized_user_id)
                )
            ).first()
            return self._row_to_user(row) if row else None

    def get_user_by_account_type(self, account: str, account_type: str) -> StoredUser | None:
        self._prune_expired()
        normalized = normalize_account_identifier(account, account_type)
        with self._session() as session:
            if account_type == "email":
                row = session.scalars(select(UserRow).where(UserRow.email == normalized)).first()
            elif account_type == "mobile":
                row = session.scalars(select(UserRow).where(UserRow.mobile == normalized)).first()
            else:
                row = None
            return self._row_to_user(row) if row else None

    def get_admin_by_id(self, admin_id: str) -> StoredAdmin | None:
        self._prune_expired()
        with self._session() as session:
            row = session.get(AdminRow, admin_id)
            return self._row_to_admin(row) if row else None

    def get_admin_by_username(self, username: str) -> StoredAdmin | None:
        self._prune_expired()
        with self._session() as session:
            row = session.scalars(select(AdminRow).where(AdminRow.username == username.strip().lower())).first()
            return self._row_to_admin(row) if row else None

    def verify_user_password(self, user: StoredUser, password: str) -> bool:
        return user.password_hash == _hash_password(password)

    def verify_admin_password(self, admin: StoredAdmin, password: str) -> bool:
        return admin.password_hash == _hash_password(password)

    def issue_verification_code(self, *, scene: str, account: str, account_type: str) -> StoredVerificationCode:
        self._prune_expired()
        normalized_account = normalize_account_identifier(account, account_type)
        with self._lock:
            with self._session_factory.begin() as session:
                existing = session.scalars(
                    select(VerificationCodeRow).where(
                        VerificationCodeRow.scene == scene,
                        VerificationCodeRow.account == normalized_account,
                        VerificationCodeRow.account_type == account_type,
                    )
                ).first()
                if existing is not None:
                    return self._row_to_verification_code(existing)
                created_at = datetime.now(UTC)
                expires_at = created_at + timedelta(seconds=self.settings.verification_code_ttl_seconds)
                record = VerificationCodeRow(
                    scene=scene,
                    account=normalized_account,
                    account_type=account_type,
                    code=self.settings.verification_code_value,
                    created_at=created_at,
                    expires_at=expires_at,
                )
                session.add(record)
            self._snapshot = self._load_snapshot()
        return StoredVerificationCode(
            scene=scene,
            account=normalized_account,
            account_type=account_type,
            code=self.settings.verification_code_value,
            created_at=created_at.isoformat(),
            expires_at=expires_at.isoformat(),
        )

    def verify_code(self, *, scene: str, account: str, account_type: str, code: str) -> bool:
        self._prune_expired()
        normalized_account = normalize_account_identifier(account, account_type)
        with self._session() as session:
            row = session.scalars(
                select(VerificationCodeRow).where(
                    VerificationCodeRow.scene == scene,
                    VerificationCodeRow.account == normalized_account,
                    VerificationCodeRow.account_type == account_type,
                    VerificationCodeRow.code == code,
                )
            ).first()
            return row is not None

    def consume_verification_code(self, *, scene: str, account: str, account_type: str, code: str) -> bool:
        self._prune_expired()
        normalized_account = normalize_account_identifier(account, account_type)
        with self._lock:
            with self._session_factory.begin() as session:
                row = session.scalars(
                    select(VerificationCodeRow).where(
                        VerificationCodeRow.scene == scene,
                        VerificationCodeRow.account == normalized_account,
                        VerificationCodeRow.account_type == account_type,
                        VerificationCodeRow.code == code,
                    )
                ).first()
                if row is None:
                    return False
                session.delete(row)
            self._snapshot = self._load_snapshot()
        return True

    def create_password_challenge(
        self,
        *,
        account: str,
        account_type: str,
        verification_code: str,
    ) -> StoredPasswordChallenge:
        self._prune_expired()
        normalized_account = normalize_account_identifier(account, account_type)
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(seconds=self.settings.reset_challenge_ttl_seconds)
        challenge = PasswordChallengeRow(
            challenge_id=f"pwd_challenge_{uuid4().hex[:12]}",
            account=normalized_account,
            account_type=account_type,
            verification_code=verification_code,
            created_at=created_at,
            expires_at=expires_at,
        )
        with self._lock:
            with self._session_factory.begin() as session:
                existing = session.scalars(
                    select(PasswordChallengeRow).where(
                        PasswordChallengeRow.account == normalized_account,
                        PasswordChallengeRow.account_type == account_type,
                    )
                ).all()
                for item in existing:
                    session.delete(item)
                session.add(challenge)
            self._snapshot = self._load_snapshot()
        return self._row_to_password_challenge(challenge)

    def get_password_challenge(self, challenge_id: str) -> StoredPasswordChallenge | None:
        self._prune_expired()
        with self._session() as session:
            row = session.get(PasswordChallengeRow, challenge_id)
            return self._row_to_password_challenge(row) if row else None

    def consume_password_challenge(self, challenge_id: str) -> None:
        with self._lock:
            with self._session_factory.begin() as session:
                row = session.get(PasswordChallengeRow, challenge_id)
                if row is not None:
                    session.delete(row)
            self._snapshot = self._load_snapshot()

    def save_refresh_session(
        self,
        *,
        token_id: str,
        subject_type: str,
        subject_id: str,
        token_version: int,
        expires_at: str,
    ) -> None:
        self._prune_expired()
        expires_at_dt = _parse_datetime(expires_at)
        with self._lock:
            with self._session_factory.begin() as session:
                existing = session.get(RefreshSessionRow, token_id)
                if existing is not None:
                    session.delete(existing)
                    session.flush()
                session.add(
                    RefreshSessionRow(
                        token_id=token_id,
                        subject_type=subject_type,
                        subject_id=subject_id,
                        token_version=token_version,
                        expires_at=expires_at_dt,
                        revoked=False,
                    )
                )
            self._snapshot = self._load_snapshot()

    def get_refresh_session(self, token_id: str) -> StoredRefreshSession | None:
        self._prune_expired()
        with self._session() as session:
            row = session.get(RefreshSessionRow, token_id)
            return self._row_to_refresh_session(row) if row else None

    def revoke_refresh_session(self, token_id: str) -> None:
        with self._lock:
            with self._session_factory.begin() as session:
                row = session.get(RefreshSessionRow, token_id)
                if row is not None:
                    row.revoked = True
            self._snapshot = self._load_snapshot()

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
            with self._session_factory.begin() as session:
                existing = session.get(RevokedAccessTokenRow, token_id)
                if existing is not None:
                    session.delete(existing)
                    session.flush()
                session.add(
                    RevokedAccessTokenRow(
                        token_id=token_id,
                        subject_type=subject_type,
                        subject_id=subject_id,
                        expires_at=_parse_datetime(expires_at),
                        revoked_at=datetime.now(UTC),
                    )
                )
            self._snapshot = self._load_snapshot()

    def is_access_token_revoked(
        self,
        *,
        token_id: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
    ) -> bool:
        if not token_id:
            return False
        self._prune_expired()
        with self._session() as session:
            row = session.get(RevokedAccessTokenRow, token_id)
            if row is None:
                return False
            if subject_type is not None and row.subject_type != subject_type:
                return False
            if subject_id is not None and row.subject_id != subject_id:
                return False
            return True

    def revoke_subject_refresh_sessions(self, subject_type: str, subject_id: str) -> None:
        with self._lock:
            with self._session_factory.begin() as session:
                rows = session.scalars(
                    select(RefreshSessionRow).where(
                        RefreshSessionRow.subject_type == subject_type,
                        RefreshSessionRow.subject_id == subject_id,
                    )
                ).all()
                for item in rows:
                    item.revoked = True
            self._snapshot = self._load_snapshot()

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
            with self._session_factory.begin() as session:
                row = session.get(UserRow, user_id)
                if row is None:
                    raise KeyError(user_id)
                if name is not UNSET and name is not None:
                    row.name = name
                if avatar_url is not UNSET:
                    row.avatar_url = avatar_url
                if locale is not UNSET and locale is not None:
                    row.locale = locale
                if time_zone is not UNSET and time_zone is not None:
                    row.time_zone = time_zone
                result = self._row_to_user(row)
            self._snapshot = self._load_snapshot()
        return result

    def change_user_password(self, user_id: str, *, old_password: str, new_password: str) -> StoredUser | None:
        with self._lock:
            with self._session_factory.begin() as session:
                row = session.get(UserRow, user_id)
                if row is None or row.password_hash != _hash_password(old_password):
                    return None
                row.password_hash = _hash_password(new_password)
                row.token_version += 1
                result = self._row_to_user(row)
            self._snapshot = self._load_snapshot()
        return result

    def reset_user_password(self, *, account: str, account_type: str, new_password: str) -> StoredUser | None:
        normalized = normalize_account_identifier(account, account_type)
        with self._lock:
            with self._session_factory.begin() as session:
                if account_type == "email":
                    row = session.scalars(select(UserRow).where(UserRow.email == normalized)).first()
                elif account_type == "mobile":
                    row = session.scalars(select(UserRow).where(UserRow.mobile == normalized)).first()
                else:
                    row = None
                if row is None:
                    return None
                row.password_hash = _hash_password(new_password)
                row.token_version += 1
                result = self._row_to_user(row)
            self._snapshot = self._load_snapshot()
        return result

    def create_admin_confirmation(self, *, admin_id: str, action: str, resource_scope: str) -> StoredAdminConfirmation:
        created_at = datetime.now(UTC)
        expired_at = created_at + timedelta(seconds=self.settings.admin_confirm_ttl_seconds)
        record = AdminConfirmationRow(
            confirm_token=f"confirm_{uuid4().hex[:16]}",
            admin_id=admin_id,
            action=action,
            resource_scope=resource_scope,
            created_at=created_at,
            expired_at=expired_at,
        )
        with self._lock:
            with self._session_factory.begin() as session:
                session.add(record)
            self._snapshot = self._load_snapshot()
        return self._row_to_admin_confirmation(record)

    def record_cache_invalidation(self, *, subject_type: str, subject_ids: list[str]) -> None:
        with self._lock:
            with self._session_factory.begin() as session:
                session.add(
                    InvalidationEventRow(
                        subject_type=subject_type,
                        subject_ids=list(subject_ids),
                        created_at=datetime.now(UTC),
                    )
                )
            self._snapshot = self._load_snapshot()

    @staticmethod
    def _row_to_user(row: UserRow) -> StoredUser:
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
        )

    @staticmethod
    def _row_to_admin(row: AdminRow) -> StoredAdmin:
        return StoredAdmin(
            admin_id=row.admin_id,
            username=row.username,
            name=row.name,
            password_hash=row.password_hash,
            roles=list(row.roles or []),
            permissions=list(row.permissions or []),
            menus=[AdminMenuItem.model_validate(item) for item in list(row.menus or [])],
            token_version=row.token_version,
        )

    @staticmethod
    def _row_to_verification_code(row: VerificationCodeRow) -> StoredVerificationCode:
        return StoredVerificationCode(
            scene=row.scene,
            account=row.account,
            account_type=row.account_type,
            code=row.code,
            created_at=row.created_at.isoformat(),
            expires_at=row.expires_at.isoformat(),
        )

    @staticmethod
    def _row_to_password_challenge(row: PasswordChallengeRow) -> StoredPasswordChallenge:
        return StoredPasswordChallenge(
            challenge_id=row.challenge_id,
            account=row.account,
            account_type=row.account_type,
            verification_code=row.verification_code,
            created_at=row.created_at.isoformat(),
            expires_at=row.expires_at.isoformat(),
        )

    @staticmethod
    def _row_to_refresh_session(row: RefreshSessionRow) -> StoredRefreshSession:
        return StoredRefreshSession(
            token_id=row.token_id,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            token_version=row.token_version,
            expires_at=row.expires_at.isoformat(),
            revoked=row.revoked,
        )

    @staticmethod
    def _row_to_revoked_access_token(row: RevokedAccessTokenRow) -> StoredRevokedAccessToken:
        return StoredRevokedAccessToken(
            token_id=row.token_id,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            expires_at=row.expires_at.isoformat(),
            revoked_at=row.revoked_at.isoformat(),
        )

    @staticmethod
    def _row_to_admin_confirmation(row: AdminConfirmationRow) -> StoredAdminConfirmation:
        return StoredAdminConfirmation(
            confirm_token=row.confirm_token,
            admin_id=row.admin_id,
            action=row.action,
            resource_scope=row.resource_scope,
            created_at=row.created_at.isoformat(),
            expired_at=row.expired_at.isoformat(),
        )

    @staticmethod
    def _row_to_invalidation_event(row: InvalidationEventRow) -> StoredInvalidationEvent:
        return StoredInvalidationEvent(
            subject_type=row.subject_type,
            subject_ids=list(row.subject_ids or []),
            created_at=row.created_at.isoformat(),
        )


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
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _normalize_database_url(value: str) -> str:
    return value.replace("mysql://", "mysql+pymysql://", 1) if value.startswith("mysql://") else value


def _connect_args(database_url: str) -> dict[str, Any]:
    return {"check_same_thread": False} if database_url.startswith("sqlite") else {}


@lru_cache(maxsize=1)
def get_auth_store() -> AuthStore:
    return AuthStore()


def normalize_account_identifier(account: str, account_type: str | None = None) -> str:
    normalized = account.strip()
    if account_type == "email" or (account_type is None and "@" in normalized):
        return normalized.lower()
    return normalized
