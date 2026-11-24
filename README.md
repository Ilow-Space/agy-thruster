# agy-d1-glm-router

[![Antigravity Plugin](https://img.shields.io/badge/Antigravity-Plugin-4285F4)](https://antigravity.google)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Antigravity Decision-Routed Worker Plugin:** Keeps **Gemini as the interactive top-level overseer** while automatically offloading routine code editing, boilerplate, and multi-file implementation work to **SiliconFlow (`zai-org/GLM-5.3-Flash` and `zai-org/GLM-5.3`)** via a local **Liquid AI `d1:3b` decision router** (`POST /v1/systemone`).

---

## 1. Architectural Overview & Invariants

```text
                            +-------------------------------------+
                            |    Interactive User Conversation    |
                            +------------------+------------------+
                                               |
                                               v
                            +-------------------------------------+
                            |    Gemini Overseer (Antigravity)    |
                            | - Architecture & security boundaries|
                            | - Specification clarity checks      |
                            | - Git commits, diffs & review       |
                            +------------------+------------------+
                                               |
                                (Tool Call: PreToolUse)
                                               |
                                               v
                        +---------------------------------------------+
                        | scripts/pre_tool_router.py (PreToolUse Hook)|
                        +----------------------+----------------------+
                                               |
                        POST /v1/systemone     | (Timeout: 1.5s, fail-open)
                                               v
                        +---------------------------------------------+
                        |  Local Liquid AI d1:3b (Ollama / llama.cpp) |
                        |  - destination: glm-flash | heavy | native  |
                        |  - risk_level: 0.0 .. 3.0                   |
                        +----------------------+----------------------+
                                               |
                     +-------------------------+-------------------------+
                     |                                                   |
      dest == gemini-native / risk > 1.5                  dest != gemini-native, conf >= 0.70, risk <= 1.5
                     |                                                   |
                     v                                                   v
          {"decision": "allow"}                               {"decision": "deny", "reason": "ROUTER_OFFLOAD"}
                     |                                                   |
        Gemini executes tool directly                                    v
                                                        Gemini delegates via Handoff Spec:
                                                        - Subagent: `glm-worker` (native /agents)
                                                        - Direct MCP: `mcp(pi/spawn)`
                                                                         |
                                                                         v
                                                        +-----------------------------------+
                                                        | pi-delegate-mcp (Stdio Server)    |
                                                        | Backed by SiliconFlow:            |
                                                        | - zai-org/GLM-5.3-Flash           |
                                                        | - zai-org/GLM-5.3                 |
                                                        +-----------------+-----------------+
                                                                          |
                                                   State files: ~/.local/state/pi-delegate-mcp/*.json
                                                                          |
                                                                          v
                                                        +-----------------------------------+
                                                        | scripts/escalation_watcher.py     |
                                                        | - PreInvocation: Injects notes    |
                                                        | - Stop: Wakes Gemini on blocker   |
                                                        +-----------------------------------+
```

### Mandatory Compliance & Design Invariants
1. **Antigravity Consumer OAuth ToS Compliance:**
   - `agy` remains the unmodified top-level interactive agent.
   - No HTTP proxy, wrapper CLI, or outer agent harness intercepts Google OAuth traffic.
   - Interception, subagent visibility, and lifecycle hooks operate strictly through official Antigravity plugin primitives (`plugin.json`, `hooks.json`, `agents/*.md`, `skills/*/SKILL.md`, `rules/*.md`, `mcp_config.json`).
2. **Zero External Python Dependencies in Hooks:**
   - All hook scripts in `scripts/` use **Python standard library only** (`urllib.request`, `json`, `os`, `sys`, `pathlib`, `time`, `hashlib`), maintaining sub-millisecond execution with zero `pip` install friction.
3. **Context Hygiene:**
   - Never dump raw worker logs or transcripts into Gemini's context. Returned status summaries are capped to concise structured payloads (<= 400 tokens).

---

## 2. Repository Layout

```text
agy-d1-glm-router/
├── plugin.json                        # Official Antigravity v1 manifest
├── hooks.json                         # PreToolUse, PreInvocation, Stop lifecycle hooks
├── mcp_config.json                    # Stdio MCP worker server configuration
├── README.md                          # Prerequisites, env vars, install & test guide
├── .gitignore                         # Ignore .env, __pycache__, local state, .DS_Store
├── assets/
│   └── logo.svg                       # Plugin icon
├── agents/
│   └── glm-worker.md                  # Thin flash_lite wrapper for native /agents visibility
├── rules/
│   └── delegation-policy.md           # Overseer handoff & verification rules
├── skills/
│   └── glm-orchestration/
│       └── SKILL.md                   # Structured handoff spec & periodic steering workflow
├── scripts/
│   ├── common.py                      # Config loading, state tracking, structured logging
│   ├── pre_tool_router.py             # PreToolUse hook calling d1:3b /v1/systemone
│   └── escalation_watcher.py          # PreInvocation & Stop hooks for worker needs_input alerts
└── tests/
    ├── test_pre_tool_router.py        # Unit tests with mocked /v1/systemone responses
    └── test_escalation_watcher.py     # Unit tests for state file parsing & deduplication
```

---

## 3. Prerequisites & Environment Variables

### Prerequisites
- **Antigravity CLI (`agy`):** v1.5.0 or newer.
- **Python:** Python 3.8+ (standard library only).
- **Liquid AI Decision Model:** `d1:3b` running on Ollama (`ollama run d1:3b`) or `llama-server` exposing `POST /v1/systemone`.
- **SiliconFlow API Key:** For GLM models (`zai-org/GLM-5.3-Flash` and `zai-org/GLM-5.3`).
- **pi-delegate-mcp:** Stdio MCP delegate runner executable installed on PATH.

### Environment Variables
| Variable | Default | Purpose |
|---|---|---|
| `SILICONFLOW_API_KEY` | *(required for worker)* | API key passed to SiliconFlow for GLM worker inference |
| `SYSTEMONE_URL` | `http://127.0.0.1:11434` | Endpoint for local decision model (`/v1/systemone`) |
| `DECISION_MODEL` | `d1:3b` | Model name queried on the decision endpoint |
| `AGY_ROUTER_BYPASS` | `0` | Set to `1` to bypass decision routing and allow all tools directly |
| `AGY_ROUTER_DEBUG` | `0` | Set to `1` to output verbose routing and hook logs to stderr |
| `XDG_STATE_HOME` | `~/.local/state` | Directory containing `pi-delegate-mcp` worker state files |
| `XDG_CACHE_HOME` | `~/.cache` | Directory where deduplication cache (`seen_events.json`) is stored |

---

## 4. Installation & Setup

### Install via Antigravity CLI (`agy`)
Install directly from the GitHub repository:
```bash
agy plugin install https://github.com/Ilow-Space/agy-thruster
```
This automatically registers the plugin manifest, lifecycle hooks, worker subagent, delegation rules, orchestration skills, and MCP servers directly into your Antigravity environment (`~/.gemini/config/plugins/agy-d1-glm-router`).

Once installed, enable the plugin and supply your `SILICONFLOW_API_KEY`:
```bash
agy plugin enable agy-d1-glm-router
```
*(Or navigate to `/plugin` in the Antigravity settings UI to toggle it on and configure server variables.)*

### Option B: Workspace Customization (Project-Scoped)
To include the plugin specifically for a single project repository, clone it into your workspace root under `.agents/plugins/`:
```bash
git clone https://github.com/Ilow-Space/agy-thruster.git .agents/plugins/agy-d1-glm-router
```

---

## 5. Testing & Validation

### Validate Plugin Manifest & Schema
Run Antigravity's strict plugin validator:
```bash
agy plugin validate --strict .
```
Expected output:
```text
Validating agy-d1-glm-router (plugin.json)
  skills 1 · agents 1 · rules 1 · hooks 1 · mcpServers 1 · sidecars 0
✔ Validation passed
```

### Run Unit Tests
Execute the comprehensive test suite verifying router bypasses, mocked `d1:3b` decisions, fail-open behavior, and watcher state deduplication:
```bash
python -m unittest discover -s tests -v
```

---

## 6. How It Works in Practice

1. **PreToolUse Interception:**
   When Gemini attempts `write_to_file`, `replace_file_content`, or `run_command`, `pre_tool_router.py` intercepts the call:
   - Read-only commands (`git status`, `git diff`, `git log`, `agy plugin validate`) bypass immediately.
   - Subagent calls already targeting `glm-worker` bypass immediately.
   - Other calls send a compact state to `POST /v1/systemone`.
2. **Decision & Routing:**
   - If `d1:3b` classifies the destination as `glm-flash` or `glm-heavy` with `confidence >= 0.70` and `risk_level <= 1.5`, the hook denies direct execution with a structured `ROUTER_OFFLOAD` reason.
   - Otherwise, the call is allowed directly on Gemini.
3. **Structured Worker Handoff:**
   Gemini receives the offload directive and constructs a structured handoff specification according to `rules/delegation-policy.md`:
   - Goal & Context (1–3 sentences)
   - Target Files & Boundaries (explicit allowed paths)
   - Acceptance Criteria & Verification Command (`npm test`, `pytest`, etc.)
   - Escalation Triggers
4. **Execution & Escalation:**
   - The worker runs asynchronously or in background.
   - If the worker needs guidance (`needs_input`), `escalation_watcher.py` injects a system note on `PreInvocation` and prevents Gemini from stopping on `Stop` until addressed.
5. **Final Review:**
   Gemini inspects the worker's final diff (`git diff`) and test results before staging or committing changes.
