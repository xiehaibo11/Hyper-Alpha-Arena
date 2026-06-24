"""Static asset mounting for generated frontend files and local uploads."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config.storage import get_upload_storage_settings


def mount_static_assets(app: FastAPI) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    static_dir = backend_root / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    upload_storage_settings = get_upload_storage_settings()
    if upload_storage_settings.mode == "local":
        upload_dir = Path(upload_storage_settings.local_root)
        upload_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")
