#!/usr/bin/env python
"""Common utilities for agy-d1-glm-router hooks.

Uses Python 3.8+ standard library only for sub-millisecond execution
with zero pip dependencies.
"""

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
import urllib.error


def get_systemone_url() -> str:
    """Return configured or default Liquid AI /v1/systemone endpoint."""
    return os.environ.get("SYSTEMONE_URL", "http://127.0.0.1:11434").rstrip("/")


def get_decision_model() -> str:
    """Return decision model name, defaulting to d1:3b."""
    return os.environ.get("DECISION_MODEL", "d1:3b")


def get_state_dir() -> Path:
    """Return state directory for pi-delegate-mcp state files."""
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        base = Path(xdg_state)
    else:
        base = Path.home() / ".local" / "state"
    return base / "pi-delegate-mcp"


def get_cache_dir() -> Path:
    """Return cache directory for agy-d1-glm-router."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        base = Path(xdg_cache)
    else:
        base = Path.home() / ".cache"
    return base / "agy-d1-glm-router"


def get_seen_events_file() -> Path:
    """Return path to seen_events.json."""
    return get_cache_dir() / "seen_events.json"


def load_seen_events() -> set:
    """Load previously surfaced event identifiers from cache."""
    cache_file = get_seen_events_file()
    if not cache_file.exists():
        return set()
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(data)
            elif isinstance(data, dict):
                return set(data.keys())
    except Exception as exc:
        log_warning(f"Failed to read seen_events.json: {exc}")
    return set()


def save_seen_events(seen_events: set) -> None:
    """Persist surfaced event identifiers to cache."""
    cache_file = get_seen_events_file()
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        # atomic write via temp file
        temp_file = cache_file.with_suffix(f".tmp.{os.getpid()}")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(sorted(list(seen_events)), f, indent=2)
        temp_file.replace(cache_file)
    except Exception as exc:
        log_warning(f"Failed to save seen_events.json: {exc}")


def read_stdin_json() -> dict:
    """Read and parse JSON from stdin."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception as exc:
        log_warning(f"Failed to parse stdin JSON: {exc}")
        return {}


def write_stdout_json(payload: dict) -> None:
    """Write structured JSON payload to stdout and flush."""
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def log_debug(message: str) -> None:
    """Write debug log to stderr if AGY_ROUTER_DEBUG is enabled."""
    if os.environ.get("AGY_ROUTER_DEBUG") == "1":
        sys.stderr.write(f"[agy-d1-glm-router DEBUG] {message}\n")
        sys.stderr.flush()


def log_warning(message: str) -> None:
    """Write warning log to stderr."""
    sys.stderr.write(f"[agy-d1-glm-router WARN] {message}\n")
    sys.stderr.flush()


def log_error(message: str) -> None:
    """Write error log to stderr."""
    sys.stderr.write(f"[agy-d1-glm-router ERROR] {message}\n")
    sys.stderr.flush()
