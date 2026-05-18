"""Operator-mode project tools for Hyper AI.

The user can delegate engineering repairs to Hyper AI through these tools.
They intentionally work inside the project boundary and keep hard stops around
secrets, destructive filesystem operations, database wipes, and real trading.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKUP_ROOT = PROJECT_ROOT / ".hyper_ai_backups"

SECRET_PATH_PATTERNS = (
    ".env",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    "id_rsa",
    "id_ed25519",
    "frontend/public/vpn",
    "backend/static/vpn",
    "代理服务vpn订阅",
)

SECRET_TEXT_RE = re.compile(
    r"(api[_-]?key|secret|token|password|private[_-]?key|DATABASE_URL|wallet|mnemonic)",
    re.IGNORECASE,
)

DESTRUCTIVE_COMMAND_RE = re.compile(
    r"("
    r"rm\s+-rf|"
    r"git\s+reset|git\s+checkout|git\s+clean|"
    r"mkfs|shutdown|reboot|poweroff|"
    r"dd\s+if=|"
    r"drop\s+database|truncate\s+table|delete\s+from|"
    r"docker\s+compose\s+down\s+-v|"
    r"chmod\s+-R\s+777|chown\s+-R|"
    r"curl\s+[^|;&]*\|\s*(sh|bash)|wget\s+[^|;&]*\|\s*(sh|bash)|"
    r"scp\s+|rsync\s+|nc\s+|netcat\s+|ftp\s+|sftp\s+|"
    r"env\b|printenv\b|/proc/self/environ"
    r")",
    re.IGNORECASE,
)


def _json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def _safe_relpath(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT))


def _is_secret_path(path: Path) -> bool:
    text = str(path.relative_to(PROJECT_ROOT)).lower()
    name = path.name.lower()
    return any(pattern in text or pattern in name for pattern in SECRET_PATH_PATTERNS)


def _resolve_path(path: str, *, for_write: bool = False) -> Path:
    if not path or not str(path).strip():
        raise ValueError("path is required")
    raw = Path(str(path).strip())
    resolved = raw.resolve() if raw.is_absolute() else (PROJECT_ROOT / raw).resolve()
    if PROJECT_ROOT not in [resolved, *resolved.parents]:
        raise ValueError("path must stay inside the project root")
    if ".git" in resolved.parts or "node_modules" in resolved.parts or ".venv" in resolved.parts:
        raise ValueError("path is inside a blocked runtime/vendor directory")
    if _is_secret_path(resolved):
        raise ValueError("path is blocked because it may contain credentials or private subscription data")
    if for_write and resolved.is_dir():
        raise ValueError("cannot write a directory")
    return resolved


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mask_output(text: str) -> str:
    masked = SECRET_TEXT_RE.sub("***", text or "")
    return masked[:12000]


def _safe_env() -> Dict[str, str]:
    blocked = re.compile(r"(key|secret|token|password|private|database_url|wallet|mnemonic)", re.IGNORECASE)
    return {key: value for key, value in os.environ.items() if not blocked.search(key)}


def execute_read_project_file(
    path: str,
    start_line: int = 1,
    end_line: Optional[int] = None,
    max_chars: int = 20000,
) -> str:
    """Read a non-secret project file for Hyper AI engineering work."""
    try:
        target = _resolve_path(path)
        if not target.exists() or not target.is_file():
            return _json({"status": "error", "error": "file not found", "path": path})
        max_chars = min(max(int(max_chars or 20000), 1000), 60000)
        start_line = max(int(start_line or 1), 1)
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        end = int(end_line) if end_line else len(lines)
        end = min(max(end, start_line), len(lines))
        selected = "\n".join(lines[start_line - 1:end])
        truncated = len(selected) > max_chars
        if truncated:
            selected = selected[:max_chars]
        return _json({
            "status": "ok",
            "path": _safe_relpath(target),
            "start_line": start_line,
            "end_line": end,
            "total_lines": len(lines),
            "sha256": _sha256_bytes(target.read_bytes()),
            "truncated": truncated,
            "content": selected,
        })
    except Exception as exc:
        return _json({"status": "blocked", "error": str(exc), "path": path})


def execute_write_project_file(
    path: str,
    content: str,
    expected_sha256: Optional[str] = None,
    create: bool = False,
    reason: Optional[str] = None,
) -> str:
    """Write a non-secret project file, preserving a timestamped backup."""
    try:
        target = _resolve_path(path, for_write=True)
        if target.exists() and not target.is_file():
            return _json({"status": "blocked", "error": "target is not a file", "path": path})
        if not target.exists() and not create:
            return _json({"status": "blocked", "error": "file does not exist; pass create=true", "path": path})
        if content is None:
            return _json({"status": "blocked", "error": "content is required", "path": path})
        encoded = str(content).encode("utf-8")
        if len(encoded) > 350_000:
            return _json({"status": "blocked", "error": "content too large for operator write", "path": path})

        before_sha = None
        backup_path = None
        if target.exists():
            before_bytes = target.read_bytes()
            before_sha = _sha256_bytes(before_bytes)
            if expected_sha256 and expected_sha256 != before_sha:
                return _json({
                    "status": "blocked",
                    "error": "expected_sha256 does not match current file",
                    "path": _safe_relpath(target),
                    "current_sha256": before_sha,
                })
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            backup_path = BACKUP_ROOT / timestamp / _safe_relpath(target)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_path)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        after_sha = _sha256_bytes(encoded)
        return _json({
            "status": "ok",
            "path": _safe_relpath(target),
            "created": before_sha is None,
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "bytes": len(encoded),
            "backup_path": _safe_relpath(backup_path) if backup_path else None,
            "reason": reason,
        })
    except Exception as exc:
        return _json({"status": "blocked", "error": str(exc), "path": path})


def execute_run_project_command(
    command: str,
    working_dir: str = ".",
    timeout_seconds: int = 60,
    reason: Optional[str] = None,
) -> str:
    """Run an engineering command inside the project with destructive operations blocked."""
    try:
        command = str(command or "").strip()
        if not command:
            return _json({"status": "blocked", "error": "command is required"})
        if len(command) > 1200:
            return _json({"status": "blocked", "error": "command is too long"})
        if _is_command_blocked(command):
            return _json({
                "status": "blocked",
                "error": "command blocked by operator-mode safety policy",
                "command": command,
            })
        cwd = _resolve_path(working_dir)
        if not cwd.is_dir():
            return _json({"status": "blocked", "error": "working_dir is not a directory", "working_dir": working_dir})
        timeout_seconds = min(max(int(timeout_seconds or 60), 1), 180)
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            env=_safe_env(),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return _json({
            "status": "ok" if completed.returncode == 0 else "error",
            "command": command,
            "working_dir": _safe_relpath(cwd),
            "returncode": completed.returncode,
            "stdout": _mask_output(completed.stdout),
            "stderr": _mask_output(completed.stderr),
            "reason": reason,
        })
    except subprocess.TimeoutExpired as exc:
        return _json({
            "status": "error",
            "error": f"command timed out after {exc.timeout}s",
            "stdout": _mask_output(exc.stdout or ""),
            "stderr": _mask_output(exc.stderr or ""),
        })
    except Exception as exc:
        return _json({"status": "blocked", "error": str(exc), "command": command})


def _is_command_blocked(command: str) -> bool:
    lowered = command.lower()
    if DESTRUCTIVE_COMMAND_RE.search(command):
        return True
    if _is_unsafe_rg_command(lowered):
        return True
    if any(pattern in lowered for pattern in SECRET_PATH_PATTERNS):
        return True
    if SECRET_TEXT_RE.search(command) and not _looks_like_safe_compile_or_test(command):
        return True
    if "curl" in lowered and not any(host in lowered for host in ("127.0.0.1", "localhost")):
        return True
    return False


def _is_unsafe_rg_command(lowered: str) -> bool:
    if not lowered.startswith("rg "):
        return False
    if "--hidden" in lowered or "-uuu" in lowered or " -uu" in lowered:
        return True
    safe_scopes = (" backend", " frontend", " scripts", " deploy", " claude架构", " 配置.md", " 报错.md")
    if "--files" in lowered:
        return not any(scope in lowered for scope in safe_scopes)
    if " ." in lowered and not any(scope in lowered for scope in safe_scopes):
        return True
    return False


def _looks_like_safe_compile_or_test(command: str) -> bool:
    allowed_fragments = (
        "py_compile",
        "pytest",
        "pnpm build",
        "pnpm lint",
        "git diff",
        "git status",
    )
    lowered = command.lower()
    return any(fragment in lowered for fragment in allowed_fragments)


def execute_restart_backend_service(reason: Optional[str] = None, delay_seconds: int = 2) -> str:
    """Schedule a graceful backend restart on port 8802."""
    try:
        delay_seconds = min(max(int(delay_seconds or 2), 1), 20)
        old_pid = os.getpid()
        script = f"""
sleep {delay_seconds}
old_pid={old_pid}
kill -TERM "$old_pid" 2>/dev/null || true
sleep 6
if kill -0 "$old_pid" 2>/dev/null; then
  kill -KILL "$old_pid" 2>/dev/null || true
fi
cd {PROJECT_ROOT}/backend
nohup .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8802 > /tmp/hyper-alpha-arena-8802.log 2>&1 &
"""
        subprocess.Popen(
            ["bash", "-lc", script],
            cwd=str(PROJECT_ROOT),
            env=_safe_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return _json({
            "status": "scheduled",
            "executed": True,
            "old_pid": old_pid,
            "delay_seconds": delay_seconds,
            "health_check": "http://127.0.0.1:8802/api/health",
            "reason": reason,
            "note": "The current Hyper AI stream may disconnect while the backend restarts.",
        })
    except Exception as exc:
        return _json({"status": "error", "executed": False, "error": str(exc), "reason": reason})
