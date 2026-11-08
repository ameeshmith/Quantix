"""Authentication middleware for HTTP/streamable transport."""

import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing Bearer token authentication on HTTP endpoints."""

    def __init__(self, app, api_key: Optional[str] = None):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next) -> Response:
        # Whitelist /health endpoint
        if request.url.path in ("/health", "/healthz"):
            return await call_next(request)

        # If no API key configured, pass through (or log warning)
        if not self.api_key:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return JSONResponse(
                {
                    "error": "Unauthorized",
                    "detail": "Missing Authorization header with Bearer token.",
                },
                status_code=401,
            )

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return JSONResponse(
                {
                    "error": "Unauthorized",
                    "detail": (
                        "Invalid Authorization header format. "
                        "Expected 'Bearer <token>'."
                    ),
                },
                status_code=401,
            )

        token = parts[1]
        if token != self.api_key:
            return JSONResponse(
                {"error": "Forbidden", "detail": "Invalid API key token."},
                status_code=401,
            )

        return await call_next(request)
