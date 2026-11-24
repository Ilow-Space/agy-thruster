#!/usr/bin/env python
"""Escalation & Completion Wake-Up Watcher Hook.

Handles PreInvocation and Stop lifecycle events:
- Scans ${XDG_STATE_HOME:-~/.local/state}/pi-delegate-mcp/ for active delegate state files.
- Filters states matching the current workspace (cwd).
- Deduplicates transitions via ${XDG_CACHE_HOME:-~/.cache}/agy-d1-glm-router/seen_events.json.
- On PreInvocation: injects concise system notes for newly transitioned workers.
- On Stop: returns {"decision": "continue", "reason": "..."} if a worker needs input.
"""

import json
import os
from pathlib import Path
import sys

# Ensure sibling scripts can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common


def normalize_path(path_str: str) -> str:
    """Normalize file path for cross-platform matching."""
    if not path_str:
        return ""
    try:
        resolved = Path(path_str).resolve()
        norm = str(resolved).replace("\\", "/")
        if sys.platform == "win32":
            norm = norm.lower()
        return norm
    except Exception:
        norm = os.path.normpath(path_str).replace("\\", "/")
        if sys.platform == "win32":
            norm = norm.lower()
        return norm


def is_workspace_match(delegate_cwd: str, current_cwd: str) -> bool:
    """Check if delegate workspace matches current workspace directory."""
    if not delegate_cwd or not current_cwd:
        return True
    norm_del = normalize_path(delegate_cwd)
    norm_cur = normalize_path(current_cwd)
    return norm_del == norm_cur or norm_del.startswith(norm_cur) or norm_cur.startswith(norm_del)


def scan_unseen_delegate_events(current_cwd: str, seen_events: set) -> tuple:
    """Scan state directory and return newly transitioned events and updated seen set.

    Returns:
        (new_events, updated_seen_events)
    """
    state_dir = common.get_state_dir()
    if not state_dir.exists() or not state_dir.is_dir():
        return [], seen_events

    new_events = []
    updated_seen = set(seen_events)

    try:
        state_files = list(state_dir.glob("*.json"))
    except Exception as exc:
        common.log_warning(f"Failed to list delegate state files in {state_dir}: {exc}")
        return [], seen_events

    for file_path in state_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as exc:
            common.log_warning(f"Failed reading state file {file_path}: {exc}")
            continue

        delegate_id = (
            state.get("delegate_id")
            or state.get("id")
            or file_path.stem
        )
        status = state.get("status", "unknown").lower()
        updated_at = str(
            state.get("updated_at")
            or state.get("timestamp")
            or file_path.stat().st_mtime
        )
        delegate_cwd = state.get("cwd") or state.get("workspace") or ""

        if not is_workspace_match(delegate_cwd, current_cwd):
            continue

        event_key = f"{delegate_id}:{status}:{updated_at}"
        if event_key in updated_seen:
            continue

        # Extract summary / question / blocker
        question_or_summary = (
            state.get("question")
            or state.get("blocker")
            or state.get("message")
            or state.get("summary")
            or state.get("error")
            or f"Worker status updated to {status}"
        )

        new_events.append({
            "delegate_id": delegate_id,
            "status": status,
            "updated_at": updated_at,
            "summary": str(question_or_summary)[:300],
            "event_key": event_key,
        })
        updated_seen.add(event_key)

    return new_events, updated_seen


def handle_pre_invocation(data: dict) -> None:
    """Process PreInvocation event: inject system notes for newly transitioned workers."""
    current_cwd = data.get("cwd") or os.getcwd()
    seen_events = common.load_seen_events()
    new_events, updated_seen = scan_unseen_delegate_events(current_cwd, seen_events)

    if not new_events:
        common.write_stdout_json({"injectSteps": []})
        return

    # Filter events worth surfacing in PreInvocation: needs_input, waiting_for_answer, completed, failed
    surfaced = [
        e for e in new_events
        if e["status"] in ("needs_input", "waiting_for_answer", "completed", "failed")
    ]

    if not surfaced:
        common.save_seen_events(updated_seen)
        common.write_stdout_json({"injectSteps": []})
        return

    messages = []
    for item in surfaced:
        msg = f"Background GLM worker {item['delegate_id']} ({item['status']}): {item['summary']}"
        messages.append(msg)

    combined_text = "\n".join(messages)
    payload = {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": combined_text
                }
            }
        ]
    }

    common.save_seen_events(updated_seen)
    common.write_stdout_json(payload)


def handle_stop(data: dict) -> None:
    """Process Stop event: prevent stopping if an unread needs_input escalation just occurred."""
    # Prevent infinite continuation loop if Stop already triggered continuation this turn
    if data.get("continuationActive"):
        common.write_stdout_json({"decision": "allow"})
        return

    current_cwd = data.get("cwd") or os.getcwd()
    seen_events = common.load_seen_events()
    new_events, updated_seen = scan_unseen_delegate_events(current_cwd, seen_events)

    needs_input_events = [
        e for e in new_events
        if e["status"] in ("needs_input", "waiting_for_answer")
    ]

    if needs_input_events:
        item = needs_input_events[0]
        reason = f"Background GLM worker requires input: [{item['delegate_id']}] {item['summary']}"
        common.save_seen_events(updated_seen)
        common.write_stdout_json({"decision": "continue", "reason": reason})
    else:
        if new_events:
            common.save_seen_events(updated_seen)
        common.write_stdout_json({"decision": "allow"})


def main() -> None:
    data = common.read_stdin_json()
    event_name = data.get("hookEventName")

    # If hookEventName is not explicitly sent, detect by signature fields
    if not event_name:
        if "terminationReason" in data or "executionNum" in data:
            event_name = "Stop"
        else:
            event_name = "PreInvocation"

    if event_name == "Stop":
        handle_stop(data)
    else:
        handle_pre_invocation(data)


if __name__ == "__main__":
    main()
