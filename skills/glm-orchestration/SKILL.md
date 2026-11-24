---
name: glm-orchestration
description: Structured handoff specification and periodic steering workflow for delegating implementation tasks to SiliconFlow GLM models via local Liquid AI d1:3b router.
---

# GLM Orchestration Skill

Use this skill when receiving a `ROUTER_OFFLOAD` notification or when delegating implementation, refactoring, or test-writing tasks to SiliconFlow GLM models (`zai-org/GLM-5.3-Flash` and `zai-org/GLM-5.3`).

## Overview

Gemini acts as the interactive overseer, retaining ownership of requirements, architecture, security, and Git operations. Implementation tasks are delegated to GLM workers via `pi-delegate-mcp` or the `glm-worker` subagent.

## Delegation Workflow

### Step 1: Formulate the Handoff Specification

Prepare the specification according to the mandatory template:
1. **Goal & Context:** Brief 1–3 sentence objective.
2. **Target Files & Boundaries:** Allowed paths only.
3. **Acceptance Criteria & Verification Command:** Exact verification command (e.g., `pytest tests/`, `npm test`).
4. **Escalation Triggers:** Blocker conditions requiring human/Gemini steer.

### Step 2: Choose Delegation Vehicle

- **Subagent Delegation (`glm-worker`):**
  Call `invoke_subagent` with `TypeName: "glm-worker"` when the task involves multi-step refactoring, multi-file implementation, or needs background visibility in `/agents`.
- **Direct MCP Spawn (`mcp(pi/spawn)`):**
  Call `pi/spawn` directly for single-file, atomic, or quick mechanical changes. Always pass write tool permissions explicitly:
  `tools: ["write_to_file", "replace_file_content", "run_command"]` because `pi-delegate-mcp` workers default to read-only mode.

### Step 3: Monitor & Periodic Steering

For long-running tasks:
1. Set a one-shot wake-up timer: `schedule(DurationSeconds: 45)` (or 60).
2. Upon wake-up or escalation event, check `pi/status`.
3. If the worker requested guidance (`needs_input`), forward instructions using `pi/steer`.

### Step 4: Final Verification & Review

1. When the worker completes, inspect the modified files.
2. Run the verification command to confirm tests pass independently.
3. Run `git diff` to review all changes against architectural standards before staging or committing.
