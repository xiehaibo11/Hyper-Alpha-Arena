"""Frontend rebuild and optional local watcher helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

_frontend_watcher_thread: threading.Thread | None = None
_last_build_time = 0.0


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _sync_frontend_dist(dist_dir: Path, static_dir: Path) -> None:
    """Replace generated frontend static files without leaving stale hashed assets."""
    dist_path = dist_dir.resolve()
    static_path = static_dir.resolve()
    if static_path.name != "static":
        raise RuntimeError(f"Refusing to sync frontend build into unexpected path: {static_path}")

    static_path.mkdir(parents=True, exist_ok=True)
    for child in static_path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    for child in dist_path.iterdir():
        target = static_path / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def build_frontend() -> None:
    """Build frontend and copy the generated files into backend/static."""
    global _last_build_time
    current_time = time.time()
    if current_time - _last_build_time < 5:
        return

    frontend_dir = _project_root() / "frontend"
    static_dir = _backend_root() / "static"

    try:
        print("Frontend files changed, rebuilding...")
        result = subprocess.run(
            ["pnpm", "build"],
            cwd=frontend_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            print(f"ERROR: Frontend build failed: {result.stderr}")
            return

        dist_dir = frontend_dir / "dist"
        if not dist_dir.exists():
            print("ERROR: Frontend dist directory not found after build")
            return

        _sync_frontend_dist(dist_dir, static_dir)
        print("Frontend rebuilt and deployed successfully")
        _last_build_time = current_time
    except subprocess.TimeoutExpired:
        print("ERROR: Frontend build timed out")
    except Exception as exc:
        print(f"ERROR: Frontend build failed: {exc}")


def _frontend_watcher_enabled() -> bool:
    return os.getenv("FRONTEND_WATCHER_ENABLED", "").lower() in {"1", "true", "yes", "on"}


def _collect_file_times(frontend_dir: Path) -> dict[Path, float]:
    watch_extensions = {".tsx", ".ts", ".jsx", ".js", ".css", ".html", ".json"}
    times: dict[Path, float] = {}
    for root, dirs, files in os.walk(frontend_dir):
        dirs[:] = [d for d in dirs if d not in ["node_modules", "dist", ".git"]]
        for file_name in files:
            if any(file_name.endswith(ext) for ext in watch_extensions):
                file_path = Path(root) / file_name
                try:
                    times[file_path] = file_path.stat().st_mtime
                except OSError:
                    pass
    return times


def _watch_frontend_files() -> None:
    if not _frontend_watcher_enabled():
        return

    frontend_dir = _project_root() / "frontend"
    if not frontend_dir.exists():
        return

    file_times = _collect_file_times(frontend_dir)
    while True:
        try:
            time.sleep(2)
            current_times = _collect_file_times(frontend_dir)
            changed = any(
                path not in file_times or file_times[path] != mtime
                for path, mtime in current_times.items()
            )
            if not changed:
                changed = any(path not in current_times for path in file_times)
            if changed:
                file_times = current_times
                build_frontend()
        except Exception as exc:
            print(f"Frontend watcher error: {exc}")
            time.sleep(5)


def start_frontend_watcher_if_enabled() -> bool:
    """Start the local frontend watcher when explicitly enabled."""
    global _frontend_watcher_thread
    if not _frontend_watcher_enabled():
        return False
    if _frontend_watcher_thread and _frontend_watcher_thread.is_alive():
        return True

    _frontend_watcher_thread = threading.Thread(target=_watch_frontend_files, daemon=True)
    _frontend_watcher_thread.start()
    return True
