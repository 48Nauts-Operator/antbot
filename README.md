# AntBot

**A privacy-first AI agent that runs entirely on your machine.**

No cloud. No data leaving your network. No compromises.

## Why This Exists

I was using [NanoBot](https://github.com/HKUDS/nanobot) — a solid open-source AI agent with tool calling, chat channels, memory, the works. Then I looked at what it was actually sending to the cloud.

**Everything.** Every file I opened, every shell command output, every directory listing. My invoices, employee documents, client proposals, network configs, private notes — all shipped off to Anthropic's servers through the tool-calling loop. Not because NanoBot is malicious — it's just how cloud-based agents work. The LLM needs context, so the agent sends it.

Here's the thing: I'm doing DevOps work on my own infrastructure. I'm reading private business documents. I don't want any of that going to a third party. Period.

So I forked NanoBot and built AntBot: **same capabilities, 100% local.**

You run an LLM on your own hardware (LM Studio, Exo, Ollama — whatever you prefer), and AntBot talks to it over localhost. Your files, your commands, your data — it all stays on your machine.

Is it a bit slower than Claude or GPT-4? Yes. Is it 100% private? Also yes. That's the trade-off, and for me it's worth it.

## What It Can Do

AntBot comes with these tools built in:

| Tool | What It Does |
|---|---|
| `read_file` | Read file contents (up to 128KB, with truncation) |
| `write_file` | Create or overwrite files |
| `edit_file` | Find-and-replace editing with diff feedback |
| `list_dir` | List directory contents with sizes, grouped by type |
| `tree` | Recursive tree view with depth control |
| `exec` | Run shell commands (with safety guards) |
| `web_search` | Search the web via Brave Search API |
| `web_fetch` | Fetch and extract content from URLs |
| `message` | Send messages to chat channels |
| `cron` | Schedule tasks and reminders (cron expressions, intervals, one-shot) |
| `spawn` | Run background subagents for parallel tasks |
| `docker` | Inspect containers, logs, stats (read-only) |
| `git` | Status, diff, log, branch, show (read-only) |
| `http_request` | REST API testing (GET/POST/PUT/DELETE/PATCH) |
| `process` | List processes, check ports (read-only) |
| `space_ant` | Scan and clean disk waste (caches, ML models, Docker, Xcode, etc.) |
| **MCP** | Connect to any MCP-compatible tool server |

Plus the full **Skills** system — drop a `SKILL.md` into `~/.antbot/workspace/skills/your-skill/` and AntBot picks it up automatically.

## What We Built On Top

The baseline is [NanoBot](https://github.com/HKUDS/nanobot), which gives us the agent loop, tool registry, session management, chat channels, memory system, and MCP support. Solid foundation.

But NanoBot was built for cloud models with massive context windows. Local models (8B-30B) have smaller windows and sometimes produce wonky JSON. So we added three layers:

### Planner (`antbot/agent/planner.py`)

Before executing anything, the Planner measures the task scope. If you ask "organize these 500 files by date," it doesn't stuff all 500 filenames into context. It:

1. **Measures** — counts files, calculates total size, estimates tokens
2. **Plans** — creates an execution plan with batches that fit the model's context window
3. **Decides** — simple task (just run it) or complex (chunk it)

Simple requests like "what time is it?" skip planning entirely. Zero overhead.

*Inspired by the chunking patterns in [smolagents](https://github.com/huggingface/smolagents) — their code-first approach showed that fewer, focused LLM calls beat dumping everything into context.*

### Guard (`antbot/agent/guard.py`)

Every tool call gets a safety review before execution. Pattern-based, no second LLM needed:

- **Blocks**: `rm -rf`, `DROP TABLE`, `kill -9`, `format`, `dd if=`, `chmod 777`, `curl | bash`
- **Flags**: access to `.env`, credentials, private keys, `~/.ssh/`
- **Checks output**: catches leaked API keys, passwords, private keys in tool results

95% of dangerous operations match simple regex patterns. No need to burn tokens on a "safety LLM."

*Concept borrowed from [PocketPaw](https://github.com/pocketpaw/pocketpaw) — their Guardian AI idea, but we implemented it as pure pattern matching instead of a second model.*

### Orchestrator (`antbot/agent/orchestrator.py`)

Coordinates the flow: Planner → Guard → Executor. For chunked tasks, each batch gets a **fresh context** — the model never accumulates stale data. Intermediate results are saved to disk and merged in a final synthesis step.

This is what makes small local models viable for large tasks. A 27B model with a 32K context window can process 10,000 files — it just does it in batches.

### Dual-Mode Tool Calling (`antbot/agent/tools/strategy.py`)

Not all local models support OpenAI-style function calling. AntBot auto-detects the model's capability and picks the right strategy:

- **Native mode** — for models with built-in function calling (GPT, Claude, Qwen, Gemma 3). Tools are passed as OpenAI `tools` parameter. Zero overhead.
- **ReAct mode** — for models without native tool support. Injects `Thought → Action → Observation` prompts and parses the model's text output into tool calls.

Detection is automatic (`tool_mode: "auto"` in config), or you can force a mode. Smart tool selection scores tools by relevance to the user's message, so smaller models aren't overwhelmed with 15+ tool definitions.

### DevOps Tools

A suite of read-only inspection tools for infrastructure work:

| Tool | Actions |
|---|---|
| `docker` | `ps`, `logs`, `inspect`, `stats` |
| `git` | `status`, `diff`, `log`, `branch`, `show` |
| `http_request` | `GET`, `POST`, `PUT`, `DELETE`, `PATCH` |
| `process` | `list`, `ports`, `check` |
| `space_ant` | `scan` (report waste), `clean` (remove safe targets) |

All DevOps tools are categorized so smart tool selection picks them when relevant.

### Space-Ant (`antbot/agent/tools/space_tool.py`)

Disk space analyzer that scans for waste across multiple categories:

- **Caches** — pip, npm, cargo, Homebrew, system caches
- **ML Models** — EXO, Hugging Face, Ollama model downloads (per-model breakdown)
- **Dev Artifacts** — `node_modules`, `__pycache__`, `.tox`, `.mypy_cache`
- **Docker** — images, volumes, build cache
- **Xcode** — iOS DeviceSupport, DerivedData, DocumentationCache
- **Temp/Installers** — `.dmg`, `.pkg`, `.iso` in Downloads

`scan` is read-only. `clean` requires `confirm=true` and handles Xcode caches, Docker prune, Homebrew cleanup, Ollama models, installers, temp files, and dev waste.

> **Platform note:** Xcode and Homebrew cleanup is macOS-only. Docker, ML models, pip/npm, temp files, and dev artifacts work cross-platform (macOS + Linux).

### Fast-Path Dispatcher (`antbot/agent/fast_path.py`)

Simple read-only queries (like `ls`, `git status`, `docker ps`, `disk usage`) are intercepted before they reach the LLM. Pattern matching routes them directly to the right tool — instant response, zero tokens spent.

A write-intent gate prevents dangerous commands from bypassing the LLM's judgment. Keywords like `delete`, `remove`, `create` always go through the full agent loop.

### JSON Repair (`antbot/utils/json_repair.py`)

Local models occasionally produce malformed JSON in tool calls. Instead of failing, AntBot runs a 7-step repair pipeline:

1. Try as-is
2. Extract from markdown code blocks
3. Find JSON start (`{` or `[`)
4. Replace single quotes with double quotes
5. Remove trailing commas
6. Close unclosed braces/brackets
7. Fall back to the `json-repair` library

### Other ideas we liked

- **[PicoAgents](https://github.com/borhen68/picoagents)** — entropy-based routing (ask the user when the model is uncertain). We haven't implemented this yet, but it's on the roadmap.
- **[mini-swe-agent](https://github.com/princeton-nlp/SWE-agent)** — proved that bash-only agents with minimal tools can be surprisingly effective. Reinforced our "less is more" philosophy.

## Architecture

```
User Request
    |
    v
PLANNER --- Measures scope, creates execution plan
    |        (skipped for simple requests)
    v
GUARD ----- Reviews tool calls for safety
    |        (pattern-based, no second LLM)
    v
EXECUTOR -- Runs plan with context isolation per batch
    |        (each batch gets fresh context)
    v
TOOLS ----- File ops | Shell | Web | MCP | Skills | Cron
    |
    v
Response
```

## Quick Start

### 1. Get a local LLM running

Pick one:

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

### 3. Configure

```bash
antbot onboard
```

Or manually edit `~/.antbot/config.json`:

```json
{
  "agents": {
    "defaults": {
      "model": "mlx-community/GLM-4.7-Flash-4bit",
      "provider": "custom"
    }
  },
  "providers": {
    "custom": {
      "apiKey": "local",
      "apiBase": "http://localhost:52415/v1"
    }
  },
  "tools": {
    "web": {
      "search": {
        "searxngUrl": "http://your-searxng-instance:9017",
        "apiKey": ""
      }
    }
  }
}
```

Point `apiBase` at wherever your LLM is running (Exo, LM Studio, Ollama). For web search, set either `searxngUrl` (self-hosted SearXNG) or `apiKey` (Brave Search API).

### 4. Run

```bash
# Interactive chat
antbot agent

# Single message
antbot agent -m "List the files in my Downloads"

# With debug logs
antbot agent -m "Hello" --logs
```

### Slash Commands

In interactive chat, these commands are available:

| Command | What It Does |
|---|---|
| `/model` | Show current model, provider, and endpoint |
| `/model list` | List all available models from endpoint (grouped tree view) |
| `/model <name>` | Switch model at runtime (fuzzy matching — short names work) |
| `/new` | Start a fresh conversation (archives memory) |
| `/stop` | Cancel all running tasks |
| `/help` | Show available commands |

Model switching is instant — no restart needed. Short names resolve automatically (e.g. `/model GLM-4.7-Flash-4bit` finds `mlx-community/GLM-4.7-Flash-4bit`).

## Recommended Models

For reliable tool calling, you need **20B+ active parameters**. MoE models with small active params (e.g. A3B = 3B active) struggle with multi-step reasoning.

| Model | Size | Active Params | Best For |
|---|---|---|---|
| GLM-4.7-Flash-4bit | 18GB | ~18B (dense) | Everyday tasks, good tool calling, thinking capable |
| Llama-3.3-70B-Instruct-4bit | 38GB | 70B (dense) | Complex reasoning, proven instruction following |
| Qwen3-235B-A22B-4bit | 132GB | 22B (MoE) | Heavy multi-step tasks (via Exo cluster) |
| Qwen3-Coder-Next-4bit | 43GB | dense | Code-focused tasks, structured output |
| Gemma 3 27B | 18GB | 27B (dense) | Good all-rounder, solid tool calling |

**Avoid for tool calling:** anything with A3B (3B active), or under 8B dense — too small for ReAct reasoning.

## Chat Channels

AntBot supports all the channels from NanoBot:

- **CLI** (built-in)
- **Telegram**
- **Discord**
- **WhatsApp** (via bridge)
- **Slack**
- **Matrix/Element**
- **Email** (IMAP/SMTP)
- **Feishu/Lark**
- **DingTalk**

Enable any channel in `~/.antbot/config.json`. Each channel has its own allow-list for access control.

## NanoBot vs AntBot

| | NanoBot | AntBot |
|---|---|---|
| **LLM** | Cloud (Claude, GPT-4) | Local (LM Studio, Exo, Ollama) |
| **Privacy** | Everything goes to cloud APIs | Nothing leaves your machine |
| **Context** | Dump everything, hope it fits | Measure → Plan → Chunk → Execute |
| **Safety** | Allow list per channel | Guard reviews every tool call |
| **JSON** | Assumes perfect formatting | 7-step repair for local model quirks |
| **Default** | Claude Opus | Whatever model you load locally |

## Project Structure

```
antbot/
├── agent/
│   ├── loop.py              # Core agent loop (executor + slash commands)
│   ├── planner.py           # Task measurement and planning
│   ├── guard.py             # Tool call safety review
│   ├── orchestrator.py      # Planner → Guard → Executor flow
│   ├── fast_path.py         # Regex-based fast-path dispatcher
│   ├── context.py           # System prompt and context builder
│   ├── memory.py            # Two-layer memory (MEMORY.md + HISTORY.md)
│   ├── skills.py            # Extensible skills system
│   ├── subagent.py          # Background subagent manager
│   └── tools/
│       ├── strategy.py      # Native vs ReAct tool-calling strategies
│       ├── react_prompt.py  # ReAct prompt templates
│       ├── filesystem.py    # read, write, edit, list_dir, tree
│       ├── shell.py         # exec (with safety guards)
│       ├── web.py           # web_search (Brave + SearXNG), web_fetch
│       ├── docker_tool.py   # Docker inspection (ps, logs, stats)
│       ├── git_tool.py      # Git operations (status, diff, log)
│       ├── http_tool.py     # HTTP requests (REST API testing)
│       ├── process_tool.py  # Process and port inspection
│       ├── space_tool.py    # Disk space analyzer + cleaner
│       ├── mcp.py           # MCP server connections
│       ├── cron.py          # Task scheduling
│       ├── message.py       # Channel messaging
│       ├── spawn.py         # Subagent spawning
│       └── registry.py      # Tool registry with Guard integration
├── providers/
│   ├── local_detect.py      # Auto-detect model capabilities + tool support
│   └── ...                  # LiteLLM + Custom + Azure provider system
├── channels/                # Telegram, Discord, WhatsApp, Slack, etc.
├── config/                  # Pydantic config schema
├── utils/
│   └── json_repair.py       # Fix malformed JSON from local models
└── cli/
    └── commands.py          # CLI interface (Typer)
```

## License

Do whatever you want with this. Seriously.

This is released under the [WTFPL](http://www.wtfpl.net/) — Do What The Fuck You Want To Public License. Clone it, fork it, sell it, rebrand it, put it on a T-shirt. We don't care.

The upstream NanoBot code is MIT licensed, which is compatible with doing whatever you want.

```
        DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE
                    Version 2, December 2004

 Copyright (C) 2026 48Nauts-Operator

 Everyone is permitted to copy and distribute verbatim or modified
 copies of this license document, and changing it is allowed as long
 as the name is changed.

            DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE
   TERMS AND CONDITIONS FOR COPYING, DISTRIBUTION AND MODIFICATION

  0. You just DO WHAT THE FUCK YOU WANT TO.
```

## Credits

- [NanoBot](https://github.com/HKUDS/nanobot) — the foundation (agent loop, tools, channels, memory)
- [PocketPaw](https://github.com/pocketpaw/pocketpaw) — Guardian AI concept (our Guard layer)
- [smolagents](https://github.com/huggingface/smolagents) — code-first efficiency patterns
- [PicoAgents](https://github.com/borhen68/picoagents) — entropy-based routing concept
- [Exo](https://github.com/exo-explore/exo) — distributed LLM inference across machines
