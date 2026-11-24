#!/usr/bin/env python
"""PreToolUse Decision Router Hook.

Intercepts routine code editing, shell, and subagent tool calls and queries
the local Liquid AI d1:3b decision model at /v1/systemone to determine whether
to offload work to SiliconFlow GLM models or keep it in top-level Gemini.
"""

import json
import os
from pathlib import Path
import re
import sys
import urllib.request
import urllib.error

# Ensure sibling scripts can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    get_decision_model,
    get_systemone_url,
    log_debug,
    log_warning,
    read_stdin_json,
    write_stdout_json,
)

READONLY_COMMAND_PATTERNS = [
    r"^\s*git\s+(status|diff|log|show|branch|rev-parse)(\s|$)",
    r"^\s*agy\s+plugin\s+validate(\s|$)",
    r"^\s*(ls|dir|pwd|echo|cat|type)(\s|$)",
    r"^\s*which\s+",
    r"^\s*where(\.exe)?\s+",
]


def is_readonly_or_inspection_command(command: str) -> bool:
    """Determine if a shell command is read-only or git inspection."""
    if not command:
        return True
    cmd = command.strip()
    for pattern in READONLY_COMMAND_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return True
    return False


def is_already_glm_worker_subagent(tool_name: str, args: dict) -> bool:
    """Determine if tool invocation is already targeting the glm-worker subagent."""
    if tool_name not in ("invoke_subagent", "subagent"):
        return False
    agent_target = (
        args.get("agent")
        or args.get("TypeName")
        or args.get("typeName")
        or args.get("Role")
        or args.get("name")
        or ""
    )
    return "glm-worker" in str(agent_target).lower()


def should_fast_path_bypass(tool_name: str, args: dict) -> bool:
    """Evaluate fast-path bypass conditions where d1:3b is not queried."""
    # 1. Explicit environment bypass
    if os.environ.get("AGY_ROUTER_BYPASS") == "1":
        log_debug("Bypassing router: AGY_ROUTER_BYPASS=1")
        return True

    # 2. Subagent already targeting glm-worker
    if is_already_glm_worker_subagent(tool_name, args):
        log_debug("Bypassing router: subagent already targets glm-worker")
        return True

    # 3. Read-only or inspection shell commands
    if tool_name == "run_command":
        cmd = args.get("CommandLine") or args.get("command") or ""
        if is_readonly_or_inspection_command(cmd):
            log_debug(f"Bypassing router: read-only/inspection command: {cmd}")
            return True

    return False


def extract_state_payload(tool_name: str, args: dict) -> dict:
    """Extract compact state representation for /v1/systemone query."""
    target_paths = []

    # Check path fields
    for key in ("Path", "path", "FilePath", "file_path", "target_path", "Paths", "paths"):
        val = args.get(key)
        if val:
            if isinstance(val, list):
                target_paths.extend([str(p) for p in val])
            else:
                target_paths.append(str(val))

    # Summary extraction
    summary = ""
    if tool_name == "run_command":
        summary = str(args.get("CommandLine") or args.get("command") or "")
    elif tool_name in ("write_to_file", "write_file"):
        content = str(args.get("Content") or args.get("content") or "")
        summary = f"write_file to {target_paths}: {content[:500]}"
    elif tool_name in ("replace_file_content", "edit_file", "multi_replace_file_content"):
        target = str(args.get("Target") or args.get("target") or "")
        replacement = str(args.get("Replacement") or args.get("replacement") or "")
        summary = f"replace in {target_paths}: target={target[:250]} -> rep={replacement[:250]}"
    elif tool_name == "invoke_subagent":
        prompt = str(args.get("Prompt") or args.get("prompt") or "")
        role = str(args.get("Role") or args.get("role") or "")
        summary = f"subagent {role}: {prompt[:500]}"
    else:
        summary = json.dumps(args)[:500]

    return {
        "tool_name": tool_name,
        "target_paths": target_paths,
        "file_count": len(target_paths) if target_paths else (1 if "file" in tool_name else 0),
        "command_summary": summary[:1500],
    }


def query_decision_model(state_payload: dict) -> tuple:
    """Query /v1/systemone decision endpoint with a 1.5s hard timeout.

    Returns:
        (destination, confidence, risk_level)
    """
    systemone_url = f"{get_systemone_url()}/v1/systemone"
    model = get_decision_model()

    request_body = {
        "model": model,
        "state": json.dumps(state_payload),
        "questions": {
            "destination": {
                "type": "choice",
                "criteria": {
                    "glm-flash": "Single-file edit, boilerplate, unit tests, mechanical refactor, or routine shell test/build command.",
                    "glm-heavy": "Multi-file feature implementation, bug fix requiring iterative test runs, or structured refactor with clear specs.",
                    "gemini-native": "High-level architecture, ambiguous requirements, security/auth/infra rules, git commits/pushes, or final diff review.",
                },
            },
            "risk_level": {
                "type": "score",
                "criteria": [
                    "Read-only or isolated local code edit",
                    "Standard reversible source file modification",
                    "Cross-module refactor or dependency change",
                    "Destructive shell command, secrets, auth, or system config",
                ],
            },
        },
    }

    try:
        req = urllib.request.Request(
            systemone_url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1.5) as response:
            resp_bytes = response.read()
            resp_data = json.loads(resp_bytes.decode("utf-8"))

        answers = resp_data.get("answers", {})
        dest_data = answers.get("destination", {})
        risk_data = answers.get("risk_level", {})

        destination = dest_data.get("choice", "gemini-native")
        confidence = float(dest_data.get("confidence", 0.0))
        risk_level = float(risk_data.get("score", 999.0))

        log_debug(f"d1:3b response: dest={destination}, conf={confidence}, risk={risk_level}")
        return destination, confidence, risk_level

    except Exception as exc:
        log_warning(f"Decision model /v1/systemone unavailable ({exc}); failing open to allow.")
        return "gemini-native", 0.0, 999.0


def main() -> None:
    data = read_stdin_json()
    tool_call = data.get("toolCall", {})
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args", {})

    if not tool_name or should_fast_path_bypass(tool_name, args):
        write_stdout_json({"decision": "allow"})
        return

    state_payload = extract_state_payload(tool_name, args)
    destination, confidence, risk_level = query_decision_model(state_payload)

    # Offload condition: destination != "gemini-native", confidence >= 0.70, risk_level <= 1.5
    if destination != "gemini-native" and confidence >= 0.70 and risk_level <= 1.5:
        reason = (
            f"ROUTER_OFFLOAD [tier={destination}, confidence={confidence:.2f}]: "
            "Offload this task to the GLM worker layer instead of executing directly on Gemini. "
            "For multi-step or background tasks you want visible in /agents, invoke subagent "
            "`glm-worker` with a complete handoff spec (goal, target files, acceptance tests, constraints). "
            "For quick atomic edits, delegate via `mcp(pi/spawn)`."
        )
        write_stdout_json({"decision": "deny", "reason": reason})
    else:
        write_stdout_json({"decision": "allow"})


if __name__ == "__main__":
    main()
