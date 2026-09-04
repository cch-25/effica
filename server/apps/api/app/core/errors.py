from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorBody


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None
    headers: dict[str, str] | None = None


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": _request_id(request),
                    "retryable": exc.retryable,
                    "details": exc.details or {},
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request did not match the API contract.",
                    "request_id": _request_id(request),
                    "retryable": False,
                    "details": {
                        "errors": [
                            {key: value for key, value in error.items() if key not in {"input", "ctx"}}
                            for error in exc.errors()
                        ]
                    },
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        code = "RESOURCE_NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "error": {
                    "code": code,
                    "message": "The requested resource was not found."
                    if exc.status_code == 404
                    else "The request could not be completed.",
                    "request_id": _request_id(request),
                    "retryable": False,
                    "details": {},
                }
            },
        )

    @app.exception_handler(ResponseValidationError)
    async def response_validation_handler(request: Request, _: ResponseValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "RESPONSE_CONTRACT_VIOLATION",
                    "message": "The server could not serialize a contract-safe response.",
                    "request_id": _request_id(request),
                    "retryable": False,
                    "details": {},
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, _: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected server error occurred.",
                    "request_id": _request_id(request),
                    "retryable": False,
                    "details": {},
                }
            },
        )


COMMON_ERROR_RESPONSES = {
    400: {"model": ErrorEnvelope, "description": "Stable domain validation error"},
    401: {"model": ErrorEnvelope, "description": "Authentication required"},
    403: {"model": ErrorEnvelope, "description": "Role, consent, or CSRF requirement failed"},
    404: {"model": ErrorEnvelope, "description": "Resource not found"},
    409: {"model": ErrorEnvelope, "description": "Version, idempotency, or state conflict"},
    410: {"model": ErrorEnvelope, "description": "Expired or permanently unavailable resource"},
    422: {"model": ErrorEnvelope, "description": "Request schema validation failed"},
    428: {"model": ErrorEnvelope, "description": "If-Match precondition is required"},
    429: {
        "model": ErrorEnvelope,
        "description": "Rate limited; Retry-After is present",
        "headers": {"Retry-After": {"schema": {"type": "integer"}}},
    },
    500: {"model": ErrorEnvelope, "description": "Contract-safe internal error"},
}
