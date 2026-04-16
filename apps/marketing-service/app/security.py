from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal
from uuid import uuid4

from app.core.config import get_settings


class TokenError(ValueError):
    pass


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime
    claims: dict[str, Any]

    @property
    def expires_in(self) -> int:
        return max(int(self.expires_at.timestamp() - time.time()), 1)


class TokenCodec:
    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str,
        internal_audience: str,
        access_ttl_minutes: int,
        algorithm: str = "HS256",
    ) -> None:
        if algorithm != "HS256":
            raise ValueError("only HS256 is supported in the local baseline")
        self.secret = secret.encode("utf-8")
        self.issuer = issuer
        self.audience = audience
        self.internal_audience = internal_audience
        self.access_ttl_minutes = access_ttl_minutes

    def issue_access_token(
        self,
        *,
        subject_type: Literal["user", "admin", "service", "agent"],
        subject_id: str,
        roles: list[str],
        permissions: list[str],
        tenant_id: str | None = None,
        token_version: int = 1,
    ) -> IssuedToken:
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=self.access_ttl_minutes)
        payload = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": subject_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "tenant_id": tenant_id,
            "roles": roles,
            "permissions": permissions,
            "token_type": "access",
            "ver": token_version,
            "jti": uuid4().hex,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        return IssuedToken(token=self._encode(payload), expires_at=expires_at, claims=payload)

    def issue_service_token(
        self,
        service_name: str,
        permissions: list[str] | None = None,
    ) -> IssuedToken:
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=self.access_ttl_minutes)
        payload = {
            "iss": self.issuer,
            "aud": self.internal_audience,
            "sub": service_name,
            "subject_type": "service",
            "subject_id": service_name,
            "tenant_id": None,
            "roles": ["service"],
            "permissions": permissions or ["service:internal.call"],
            "token_type": "access",
            "ver": 1,
            "jti": uuid4().hex,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        return IssuedToken(token=self._encode(payload), expires_at=expires_at, claims=payload)

    def decode(self, token: str) -> dict[str, Any]:
        try:
            header_part, payload_part, signature_part = token.split(".", 2)
        except ValueError as exc:
            raise TokenError("invalid token format") from exc
        signing_input = f"{header_part}.{payload_part}".encode("utf-8")
        expected_signature = _b64url_encode(hmac.new(self.secret, signing_input, hashlib.sha256).digest())
        if not hmac.compare_digest(signature_part, expected_signature):
            raise TokenError("invalid token signature")
        try:
            header = json.loads(_b64url_decode(header_part).decode("utf-8"))
            payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
        except Exception as exc:  # pragma: no cover
            raise TokenError("invalid token payload") from exc
        if header.get("alg") != "HS256":
            raise TokenError("unsupported token algorithm")
        if payload.get("iss") != self.issuer:
            raise TokenError("invalid token issuer")
        if payload.get("aud") != self.audience:
            raise TokenError("invalid token audience")
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise TokenError("token expired")
        return payload

    def _encode(self, payload: dict[str, Any]) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        header_part = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_part = _b64url_encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signing_input = f"{header_part}.{payload_part}".encode("utf-8")
        signature_part = _b64url_encode(hmac.new(self.secret, signing_input, hashlib.sha256).digest())
        return f"{header_part}.{payload_part}.{signature_part}"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("utf-8")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}".encode("utf-8"))


@lru_cache(maxsize=1)
def get_token_codec() -> TokenCodec:
    settings = get_settings()
    return TokenCodec(
        secret=settings.jwt_secret,
        issuer=settings.auth_issuer,
        audience=settings.auth_audience,
        internal_audience=settings.internal_auth_audience,
        access_ttl_minutes=settings.access_token_ttl_minutes,
        algorithm=settings.jwt_algorithm,
    )
