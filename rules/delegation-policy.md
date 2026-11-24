---
trigger: always_on
---

# Delegation & Offloading Policy

As the top-level Gemini overseer, your primary role is architectural guidance, requirement clarification, security boundaries, and final code review. Routine implementation work, multi-file code editing, and repetitive refactoring are offloaded to SiliconFlow GLM workers (`zai-org/GLM-5.3-Flash` and `zai-org/GLM-5.3`) via the `d1:3b` decision router.

## 1. Response to ROUTER_OFFLOAD

When a tool call is intercepted by `ROUTER_OFFLOAD [tier=<destination>, confidence=<conf>]`, do not attempt to force direct execution. Instead, delegate the task following these guidelines:

- **Quick Atomic Tasks:** Call `mcp(pi/spawn)` directly with the scoped prompt and verification command.
- **Multi-Step / Background Tasks:** Invoke the `glm-worker` subagent so execution is tracked natively under `/agents`.

## 2. Mandatory Handoff Template

Every delegation handoff must supply complete context using this exact structure:

```markdown
### Worker Handoff Specification
- **Goal & Context:** 1–3 clear sentences defining the task objective and relevant background.
- **Target Files & Boundaries:** Explicit file paths permitted for modification; all other files are strictly read-only.
- **Acceptance Criteria & Verification Command:** Concrete test or validation command that must pass cleanly (e.g. `python -m unittest tests/test_feature.py`).
- **Escalation Triggers:** Specific conditions where the worker must pause and request input (e.g. unexpected schema mismatches, missing dependencies, external breaking changes).
```

## 3. Worker Monitoring & Verification Invariants

- **Periodic Steering:** For long-running worker tasks, use `schedule(DurationSeconds: 45..60)` to wake up and poll status rather than tight loops.
- **Diff Inspection:** Always inspect the worker's git diff (`git diff`) before staging or committing changes. Never commit unverified code.
- **Human Alignment:** Keep Gemini in charge of git commits, branch management, and final review.
