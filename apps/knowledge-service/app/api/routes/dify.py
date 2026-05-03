from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.dify import DifyExternalKnowledgeRequest
from app.services.dify_external import (
    DifyExternalAuthError,
    DifyExternalKnowledgeService,
    DifyExternalNotConfiguredError,
    DifyExternalValidationError,
    get_dify_external_knowledge_service,
)

router = APIRouter()


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


@router.post("/retrieval")
def retrieval(payload: DifyExternalKnowledgeRequest, request: Request) -> JSONResponse:
    service: DifyExternalKnowledgeService = get_dify_external_knowledge_service()
    try:
        service.authorize(request.headers.get("Authorization"))
        response = service.retrieve(payload)
    except DifyExternalNotConfiguredError as exc:
        return _error(503, str(exc))
    except DifyExternalAuthError as exc:
        return _error(401, str(exc))
    except DifyExternalValidationError as exc:
        return _error(400, str(exc))
    return JSONResponse(status_code=200, content=response.model_dump(mode="json"))
