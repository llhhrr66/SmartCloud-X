# Change Request: Dify external knowledge adapter contract promotion

- **Date**: 2026-04-17
- **Requester**: supervisor-knowledge-rag
- **Owned services impacted**: `apps/knowledge-service`, `deploy`, future `apps/web-admin` / gateway consumers
- **Frozen areas requiring foundation follow-up**: `docs/contracts/shared/*`, `openapi/*`

## Background
Window 2 now implements an owner-local Dify External Knowledge adapter on:

- `POST /retrieval`

The adapter follows Dify's documented external knowledge request/response shape:
- bearer token auth
- `knowledge_id`
- `retrieval_setting.top_k`
- `retrieval_setting.score_threshold`
- optional `metadata_condition`
- response `records[] { content, score, title, metadata }`

This is now covered by owner tests and local/live `knowledge-rag-admin` smoke.

## Why a frozen follow-up is still needed
The current adapter is intentionally owner-local and not yet promoted into shared contracts or OpenAPI. Before other windows or downstream clients rely on it, foundation should freeze:

1. canonical route ownership
- whether `/retrieval` remains a direct service root route
- or whether a gateway/shared adapter path should be promoted instead

2. authentication contract
- canonical header expectations
- whether this adapter should reuse shared admin/internal auth primitives or remain a dedicated bearer token surface

3. metadata-condition support
- which metadata fields and comparison operators are guaranteed
- which ones stay owner-best-effort only

4. runtime status vocabulary
- how Dify adapter states should be expressed across health/snapshot/status docs
- recommended values currently used in owner scope:
  - `disabled`
  - `configured`
  - `verified-live`
  - `blocked-external`

## Requested additions
- freeze the Dify external knowledge adapter surface in shared contract docs and/or OpenAPI
- define canonical auth guidance for the adapter
- define canonical metadata filter guarantees
- define the canonical status vocabulary for Dify integration state reporting

## Compatibility notes
- this request is additive
- current owner-local implementation can remain the working baseline until promotion
- no existing owner route needs immediate removal
