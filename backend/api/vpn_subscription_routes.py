"""Serve private VPN subscription files through the live app."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["VPN Subscription"])

SUBSCRIPTION_DIR = Path(__file__).resolve().parents[1] / "static" / "vpn"
ALLOWED_FILES = {"unified.yaml", "unified.yan"}


@router.api_route("/vpn/{filename}", methods=["GET", "HEAD"])
async def get_vpn_subscription(filename: str) -> FileResponse:
    if filename not in ALLOWED_FILES:
        raise HTTPException(status_code=404, detail="Subscription file not found")

    path = SUBSCRIPTION_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Subscription file not found")

    return FileResponse(
        path,
        media_type="text/yaml",
        headers={"Cache-Control": "no-store"},
    )
