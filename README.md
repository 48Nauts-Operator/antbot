# AntBot

**A privacy-first personal machine manager — runs entirely on your machine.**

No cloud. No data leaving your network. No compromises.

## What AntBot Does

AntBot started as a local AI agent (fork of [NanoBot](https://github.com/HKUDS/nanobot)). It's evolving into a **personal machine manager** — a distributed system that watches your files, organizes your downloads, backs up your machine state, and rebuilds everything from scratch when needed.

### The Problem

You work on many projects across multiple machines. You forget to commit code, downloads pile up, dotfiles drift between machines, and when you need to wipe a computer, you spend hours setting it back up. AntBot fixes all of that.

### The Solution

```
WATCH  →  CLASSIFY  →  ACT
```

- **File triage**: Downloads, Desktop, Documents auto-sorted to NAS by rules
- **Project lifecycle**: Git repos tracked, uncommitted code flagged, backups automatic
- **System backup**: Dotfiles, SSH keys, brew packages, VS Code settings — continuously captured
- **Machine rebuild**: One command restores a fresh Mac to your exact setup via Ansible

### Architecture: Go + Python

```
Go   (antbot-exec)  =  Hands. File I/O, watching, syncing. Fast, tiny, bulletproof.
Python (antbot)     =  Brain. Decisions, rules, LLM, Telegram, Ansible.
```

The Go binary handles all file operations via gRPC (unix socket). Python makes all decisions — which files to move, where, and when. If Python is down, Go buffers events and waits.

LLM is optional. 95% of operations are deterministic pattern matching. When an LLM is needed (e.g., "is this PDF an invoice or a contract?"), requests route through [NautRouter](https://github.com/48Nauts-Operator/naut-router) for privacy-aware, cost-optimized model selection.

## Built-in Tools

| Tool | What It Does |
|---|---|
| `read_file` | Read file contents (up to 128KB, with truncation) |
| `write_file` | Create or overwrite files |
| `edit_file` | Find-and-replace editing with diff feedback |
| `list_dir` | List directory contents with sizes, grouped by type |
| `tree` | Recursive tree view with depth control |
| `exec` | Run shell commands (with safety guards) |
| `web_search` | Search the web via Brave Search API or SearXNG |
| `web_fetch` | Fetch and extract content from URLs |
| `message` | Send messages to chat channels |
| `cron` | Schedule tasks and reminders |
| `spawn` | Run background subagents for parallel tasks |
| `docker` | Inspect containers, logs, stats (read-only) |
| `git` | Status, diff, log, branch, show (read-only) |
| `http_request` | REST API testing (GET/POST/PUT/DELETE/PATCH) |
| `process` | List processes, check ports (read-only) |
| `space_ant` | Scan and clean disk waste (caches, ML models, Docker, Xcode) |
| `file_move` | Move files via Go binary with checksum verification |
| `file_copy` | Copy files via Go binary with checksum verification |
| `exec_health` | Check Go binary health status |
| **MCP** | Connect to any MCP-compatible tool server |

Plus the **Skills** system — drop a `SKILL.md` into `~/.antbot/workspace/skills/your-skill/` and AntBot picks it up automatically.

## What We Built On Top of NanoBot

The baseline is [NanoBot](https://github.com/HKUDS/nanobot) — agent loop, tool registry, session management, chat channels, memory, MCP support. We added:

### Planner (`antbot/agent/planner.py`)
Measures task scope before executing. Large jobs get chunked into batches that fit the model's context window.

### Guard (`antbot/agent/guard.py`)
Pattern-based safety review on every tool call. Blocks `rm -rf`, `DROP TABLE`, `curl | bash`, etc. No second LLM needed.

### Orchestrator (`antbot/agent/orchestrator.py`)
Coordinates Planner → Guard → Executor. Each batch gets fresh context — small models can process large tasks.

### Exec Bridge (`antbot/exec_bridge/`)
gRPC client for the Go binary. All file operations (move, copy, watch, sync) route through the Go binary for performance and reliability.

### Event Logger (`antbot/events/`)
Append-only JSONL event logging. Every action is logged — file moves, rule matches, health checks. One file per day, automatic rotation.

### Dual-Mode Tool Calling (`antbot/agent/tools/strategy.py`)
Auto-detects native function calling vs ReAct mode. 35+ local models classified.

### Fast-Path Dispatcher (`antbot/agent/fast_path.py`)
Read-only queries (`ls`, `git status`, `docker ps`) bypass the LLM entirely. Instant response, zero tokens.

## Architecture

```
┌─────────── Each Machine ────────────────────────────┐
│                                                       │
│  antbot-exec (Go, ~14MB, launchd service)            │
│  ├── File watcher (fsnotify / macOS fsevents)        │
│  ├── File operations (move/copy + SHA256 verify)     │
│  ├── Git operations (status/diff/commit/bundle)      │
│  ├── System manifest (brew/pip/npm/docker export)    │
│  ├── NAS health check                                │
│  ├── Event queue (buffer when Python is down)        │
│  └── gRPC server (unix socket only)                  │
│            │                                          │
│            │ gRPC                                     │
│            ▼                                          │
│  antbot (Python, existing 38k line codebase)         │
│  ├── Rule engine (YAML-based file routing)           │
│  ├── Exec bridge (gRPC client to Go binary)          │
│  ├── Event logger (append-only JSONL)                │
│  ├── Agent loop + Planner + Guard                    │
│  ├── Telegram bot (notifications + approvals)        │
│  ├── Ansible runner (playbook gen + provisioning)    │
│  └── 12 chat channels, 10 skills, 18 tools          │
│                                                       │
│  NautRouter (Node, optional, launchd service)        │
│  ├── Privacy-aware LLM routing                       │
│  ├── LM Studio (local) / OpenRouter / Anthropic      │
│  └── Real-time cost dashboard                        │
│                                                       │
└───────────────────────────���───────────────────────────┘
```

All processes run as native **launchd** services. No Docker dependency.

## Quick Start

### 1. Get a local LLM running

| Backend | Setup | RAM Needed |
|---|---|---|
| **[LM Studio](https://lmstudio.ai)** | Download app, load a model, start server | 8-64GB |
| **[Exo](https://github.com/exo-explore/exo)** | `pip install exo`, run `exo` on each machine | Pools across machines |
| **[Ollama](https://ollama.com)** | `brew install ollama && ollama run gemma3` | 8-64GB |

### 2. Install AntBot

```bash
git clone git@github.com:48Nauts-Operator/antbot.git
cd antbot
pip install -e .
```

### 3. Build the Go binary

```bash
cd antbot-exec
make build    # compiles binary + generates gRPC stubs
make install  # copies to ~/.antbot/bin/
```

### 4. Configure

```bash
antbot onboard
```

Or manually edit `~/.antbot/config.json`. Key settings:

```json
{
  "agents": {
    "defaults": {
      "model": "qwen3.5-4b",
      "provider": "custom"
    }
  },
  "providers": {
    "custom": {
      "apiKey": "local",
      "apiBase": "http://localhost:1234/v1"
    }
  },
  "nas": {
    "enabled": true,
    "filesRoot": "/Volumes/devhub",
    "backupRoot": "/Volumes/Tron/mpb_backup"
  },
  "execBridge": {
    "enabled": true,
    "socketPath": "/tmp/antbot.sock"
  }
}
```

### 5. Run

```bash
# Interactive chat
antbot agent

# Single message
antbot agent -m "List the files in my Downloads"

# Check exec bridge health
antbot agent -m "Check antbot-exec health"
```

## Recommended Models

| Model | Size | Best For |
|---|---|---|
| Qwen 3.5 4B | ~2.5GB VRAM | File classification, commit messages, routing decisions |
| Gemma 4 E4B | ~5GB VRAM | Fallback, multimodal document classification |
| Qwen 3.5 9B | ~5GB VRAM | Complex scaffolding, multi-step reasoning |

For file management, the LLM is optional — 95% of operations use deterministic pattern matching.

## Chat Channels

CLI (built-in), Telegram, Discord, WhatsApp (via bridge), Slack, Matrix/Element, Email (IMAP/SMTP), Feishu/Lark, DingTalk.

Enable any channel in `~/.antbot/config.json`.

## Project Structure

```
antbot/                          # Python — decision layer
├── agent/
│   ├── loop.py                  # Core agent loop
│   ├── planner.py               # Task measurement and planning
│   ├── guard.py                 # Tool call safety review
│   ├── orchestrator.py          # Planner → Guard → Executor
│   ├── fast_path.py             # Read-only fast-path dispatcher
│   └── tools/
│       ├── exec_bridge_tools.py # Go binary tools (move, copy, health)
│       ├── filesystem.py        # read, write, edit, list_dir, tree
│       ├── shell.py             # exec (with safety guards)
│       └── ...                  # 15+ more tools
├── exec_bridge/                 # gRPC client for Go binary
│   ├── client.py                # Async gRPC wrapper
│   └── manager.py               # Go binary lifecycle
├── events/                      # Append-only JSONL event logging
│   ├── schema.py                # AntBotEvent dataclass
│   └── logger.py                # JSONL writer with rotation
├── channels/                    # 12 chat channel implementations
├── config/                      # Pydantic config (NAS, rules, exec bridge)
├── providers/                   # LM Studio, Ollama, cloud (via LiteLLM)
└── cli/                         # Typer CLI

antbot-exec/                     # Go — execution layer
├── cmd/antbot-exec/main.go      # Entry point (unix socket gRPC server)
├── internal/server/server.go    # Service implementations
├── api/proto/antbot.proto       # gRPC service contracts
└── Makefile                     # build, proto gen, test, install
```

## Roadmap

- [x] **Phase 0**: Contracts + integration scaffolding (Go binary, gRPC, config, events)
- [ ] **Phase 1**: Deterministic Downloads triage (watcher, rule engine, move/copy)
- [ ] **Phase 2**: Desktop triage + operational hardening
- [ ] **Phase 3**: One-way machine backup (dotfiles, manifests)
- [ ] **Phase 4**: Bootstrap + Ansible restore
- [ ] **Phase 5**: Project protection (git bundle, commit-check)
- [ ] **Phase 6**: Optional LLM classification
- [ ] **Phase 7**: Multi-machine aggregation

See the [full spec](https://github.com/48Nauts-Operator/antbot/tree/main/docs/) for detailed architecture and build plan.

## License

[WTFPL](http://www.wtfpl.net/) — Do What The Fuck You Want To Public License.

The upstream NanoBot code is MIT licensed.

## Credits

- [NanoBot](https://github.com/HKUDS/nanobot) — the foundation (agent loop, tools, channels, memory)
- [PocketPaw](https://github.com/pocketpaw/pocketpaw) — Guardian AI concept
- [smolagents](https://github.com/huggingface/smolagents) — code-first efficiency patterns
- [Exo](https://github.com/exo-explore/exo) — distributed LLM inference
