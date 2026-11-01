# Cross-origin access: an explicit allowlist from .env, never a wildcard, never credentials
"""The frontend is served from the same origin through the Vite proxy, so most deployments need no CORS at all.

Staff authenticate with a bearer header, not cookies, so credentials are never allowed cross-origin.
"""
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware


class CorsConfigError(RuntimeError):
    pass


def install_cors(app: FastAPI, origins: tuple[str, ...]) -> None:
    if any(origin == "*" for origin in origins):
        raise CorsConfigError("CORS_ALLOWED_ORIGINS must list origins; '*' is not allowed.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
