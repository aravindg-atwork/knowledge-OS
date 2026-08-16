import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 500
    message = "Internal server error"
    code: str | None = None

    def __init__(self, message: str | None = None, code: str | None = None):
        super().__init__(message or self.message)
        if message:
            self.message = message
        if code is not None:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    message = "Resource not found"


class PermissionDeniedError(AppError):
    status_code = 403
    message = "Permission denied"


class ConflictError(AppError):
    status_code = 409
    message = "Conflict"


class TransientConnectorError(AppError):
    """Raised by connectors on retryable network/IO failures."""

    status_code = 502
    message = "Connector temporarily unavailable"


class EmailNotVerifiedError(AppError):
    status_code = 403
    code = "email_not_verified"

    def __init__(self, message: str = "Email address not verified", code: str | None = None) -> None:
        super().__init__(message, code)


class InvalidTokenError(AppError):
    status_code = 400
    code = "invalid_token"

    def __init__(self, message: str = "Invalid token", code: str | None = None) -> None:
        super().__init__(message, code)


class TokenExpiredError(AppError):
    status_code = 400
    code = "token_expired"

    def __init__(self, message: str = "Token has expired", code: str | None = None) -> None:
        super().__init__(message, code)


def register_exception_handlers(app: FastAPI, *, environment: str = "dev") -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all for bugs, not expected-failure paths (those raise AppError
        subclasses above). Always logs the real traceback server-side; only
        echoes the exception message back to the client in dev, so a stray
        stack trace / internal detail never leaks to a production caller.
        """
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        detail = str(exc) if environment == "dev" else "Internal server error"
        return JSONResponse(status_code=500, content={"detail": detail})
