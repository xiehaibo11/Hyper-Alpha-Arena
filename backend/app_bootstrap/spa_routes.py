"""Frontend SPA file routes registered after all API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def _static_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "static"


def _no_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def _is_blocked_spa_path(full_path: str) -> bool:
    blocked_names = {
        ".env",
        ".git",
        ".svn",
        ".hg",
        "config.php",
        "settings.php",
        "wp-config.php",
    }
    path_parts = [part for part in full_path.split("/") if part]
    return any(
        part.startswith(".")
        or part in blocked_names
        or part.endswith((".bak", ".backup", ".old"))
        for part in path_parts
    )


def register_spa_routes(app: FastAPI) -> None:
    @app.get("/auth-config.json")
    async def serve_auth_config():
        config_path = _static_dir() / "auth-config.json"
        if config_path.exists():
            return FileResponse(
                config_path,
                media_type="application/json",
                headers=_no_cache_headers(),
            )
        raise HTTPException(status_code=404, detail="Auth config not found")

    @app.get("/")
    async def serve_root():
        index_path = _static_dir() / "index.html"
        if index_path.exists():
            return FileResponse(index_path, headers=_no_cache_headers())
        return {"message": "Frontend not built yet"}

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith(("api", "static", "docs")):
            raise HTTPException(status_code=404, detail="Not found")
        if full_path.startswith("openapi.json") or full_path == "auth-config.json":
            raise HTTPException(status_code=404, detail="Not found")
        if _is_blocked_spa_path(full_path):
            raise HTTPException(status_code=404, detail="Not found")

        index_path = _static_dir() / "index.html"
        if index_path.exists():
            return FileResponse(index_path, headers=_no_cache_headers())
        return {"message": "Frontend not built yet"}
