from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from liyans_contracts.envelope import ErrorReceiptV1, ErrorSeverity
from pydantic import ValidationError

from liyans.core.errors import ContractError, ErrorCategory, ErrorCode, LiyanError


def error_response(request: Request, error: LiyanError) -> JSONResponse:
    receipt = ErrorReceiptV1(
        schema_version="topic3.error-receipt.v1",
        error_code=error.code.value,
        category=error.category.value,
        severity=ErrorSeverity.ERROR,
        retriable=error.retriable,
        safe_message=error.safe_message,
        details_ref=error.details or None,
        occurred_at=datetime.now(UTC),
    )
    response = JSONResponse(
        status_code=error.status_code,
        content={
            "error": receipt.model_dump(mode="json"),
            "trace_id": getattr(request.state, "trace_id", None),
        },
    )
    if error.status_code == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(LiyanError)
    async def handle_liyan_error(request: Request, exc: LiyanError) -> JSONResponse:
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            request,
            ContractError("The request did not match the required contract."),
        )

    @app.exception_handler(ValidationError)
    async def handle_model_validation(
        request: Request,
        _exc: ValidationError,
    ) -> JSONResponse:
        return error_response(
            request,
            ContractError("The payload did not match the required contract."),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            request,
            LiyanError(
                ErrorCode.INTERNAL,
                "An internal error occurred.",
                category=ErrorCategory.INTERNAL,
                status_code=500,
            ),
        )
