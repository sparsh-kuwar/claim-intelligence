"""Uniform error envelope: {"error": {"code", "message", "details"}}."""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        self.status, self.code, self.message, self.details = status, code, message, details


def _clean_validation_errors(errors) -> list[dict]:
    return [{"field": ".".join(str(p) for p in e.get("loc", []) if p != "body"), "message": e.get("msg")} for e in errors]


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status,
                            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {
            "code": "VALIDATION_ERROR", "message": "Request validation failed",
            "details": _clean_validation_errors(exc.errors())}})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):  # never leak stack traces / secrets
        return JSONResponse(status_code=500, content={"error": {
            "code": "INTERNAL_ERROR", "message": "Unexpected server error", "details": None}})
