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
      "model": "google/gemma-3-27b",
      "provider": "custom"
    }
  },
  "providers": {
    "custom": {
      "apiKey": "local",
      "apiBase": "http://localhost:1234/v1"
    }
  }
}
```

Point `apiBase` at wherever your LLM is running. That's it.

### 4. Run

```bash
# Interactive chat
antbot agent

# Single message
antbot agent -m "List the files in my Downloads"

# With debug logs
antbot agent -m "Hello" --logs
```

## Recommended Models

| Model | RAM | Best For |
|---|---|---|
| Gemma 3 9B | 6GB | Quick tasks, single tool calls |
| Gemma 3 27B | 18GB | Multi-step workflows, good tool calling |
| Qwen3-30B (Q4) | 18GB | Multi-step workflows, scripts |
| Llama 3.1-70B (Q4) | 40GB | Complex reasoning, synthesis |
| Qwen3-235B (Q4, via Exo) | 120GB | Near cloud-level quality |

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
│   ├── loop.py              # Core agent loop (executor)
│   ├── planner.py           # Task measurement and planning
│   ├── guard.py             # Tool call safety review
│   ├── orchestrator.py      # Planner → Guard → Executor flow
│   ├── context.py           # System prompt and context builder
│   ├── memory.py            # Two-layer memory (MEMORY.md + HISTORY.md)
│   ├── skills.py            # Extensible skills system
│   ├── subagent.py          # Background subagent manager
│   └── tools/
│       ├── filesystem.py    # read, write, edit, list_dir, tree
│       ├── shell.py         # exec (with safety guards)
│       ├── web.py           # web_search, web_fetch
│       ├── mcp.py           # MCP server connections
│       ├── cron.py          # Task scheduling
│       ├── message.py       # Channel messaging
│       ├── spawn.py         # Subagent spawning
│       └── registry.py      # Tool registry with Guard integration
├── providers/
│   ├── local_detect.py      # Auto-detect LM Studio / Exo / Ollama
│   └── ...                  # LiteLLM-based provider system
├── channels/                # Telegram, Discord, WhatsApp, etc.
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
