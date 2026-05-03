from __future__ import annotations

import hashlib
import math
from typing import Protocol

import httpx

from app.core.config import EmbeddingConfigurationError, Settings


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


TOKEN_PATTERN = __import__("re").compile(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]{1,}")


def tokenize_embedding_text(value: str) -> list[str]:
    return TOKEN_PATTERN.findall(value.lower())


def build_hash_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * max(dimensions, 4)
    tokens = tokenize_embedding_text(text)
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index in range(len(vector)):
            bucket = digest[index % len(digest)]
            vector[index] += (bucket / 255.0) - 0.5

    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude <= 0:
        return vector
    return [round(component / magnitude, 6) for component in vector]


class HashEmbeddingProvider:
    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [build_hash_embedding(text, self.dimensions) for text in texts]


class OpenAICompatibleEmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        missing_fields = settings.embedding_provider_missing_config()
        if missing_fields:
            joined = ", ".join(missing_fields)
            raise EmbeddingConfigurationError(
                f"embedding provider 'openai-compatible' requires: {joined}"
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self.settings.embedding_model,
            "input": texts,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.embedding_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(
            timeout=self.settings.connector_timeout_ms / 1000,
            trust_env=False,
        ) as client:
            response = client.post(self.settings.embedding_api_url.rstrip("/"), json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
        items = body.get("data") or []
        vectors = [item.get("embedding") for item in items]
        if len(vectors) != len(texts):
            raise ValueError("embedding API returned unexpected vector count")
        normalized: list[list[float]] = []
        for vector in vectors:
            if not isinstance(vector, list) or not vector:
                raise ValueError("embedding API returned an invalid embedding payload")
            normalized.append([float(value) for value in vector])
        return normalized


class FallbackEmbeddingProvider:
    def __init__(self, primary: EmbeddingProvider, fallback: EmbeddingProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.last_provider_name = fallback.__class__.__name__
        self.last_error: str | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = self.primary.embed(texts)
        except Exception as exc:
            self.last_provider_name = self.fallback.__class__.__name__
            self.last_error = str(exc)
            return self.fallback.embed(texts)
        self.last_provider_name = self.primary.__class__.__name__
        self.last_error = None
        return vectors



def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    fallback = HashEmbeddingProvider(settings.qdrant_vector_size)
    provider_name = settings.embedding_provider.strip().lower()
    if provider_name == "openai-compatible":
        return FallbackEmbeddingProvider(OpenAICompatibleEmbeddingProvider(settings), fallback)
    return fallback
