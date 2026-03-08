# AntBot Architecture

## What Is AntBot

A privacy-first personal AI agent that runs entirely on local LLMs. Forked from NanoBot, rebuilt with a planning layer that makes it work on small models (8-30B) just as well as cloud models — it just takes more batches.

**Core principle**: The LLM never sees more context than it needs. Every task is measured, planned, chunked, and executed with isolated context per step.

## Origin

- **Base**: NanoBot (MIT, github.com/HKUDS/nanobot)
- **Guard concept**: PocketPaw (Guardian AI reviews dangerous tool calls)
- **Efficiency**: smolagents (code-first = 30% fewer LLM calls)
- **Uncertainty handling**: PicoAgents (entropy routing — ask when unsure)
- **Simplicity**: mini-swe-agent (bash-only proves less is more)

## Architecture

```
┌─────────────────────────────────────────────────┐
│                    AntBot                        │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ Channels │  │   CLI    │  │   Telegram    │  │
│  │          │  │ Discord  │  │   WhatsApp    │  │
│  └────┬─────┘  └────┬─────┘  └──────┬────────┘  │
│       └──────────────┼───────────────┘           │
│                      ▼                           │
│              ┌──────────────┐                    │
│              │  Message Bus │                    │
│              └──────┬───────┘                    │
│                     ▼                            │
│  ┌─────────────────────────────────────────────┐ │
│  │              PLANNER                        │ │
│  │  1. Measure: scope the task (file count,    │ │
│  │     sizes, complexity)                      │ │
│  │  2. Plan: create execution steps            │ │
│  │  3. Decide: single-shot or chunked?         │ │
│  │                                             │ │
│  │  Lightweight LLM call (~500 tokens)         │ │
│  └──────────────────┬──────────────────────────┘ │
│                     ▼                            │
│  ┌─────────────────────────────────────────────┐ │
│  │              GUARD                          │ │
│  │  Reviews tool calls before execution:       │ │
│  │  - Destructive ops (rm, drop, kill)         │ │
│  │  - Sensitive data (passwords, keys, PII)    │ │
│  │  - External calls (API, web, push)          │ │
│  │                                             │ │
│  │  Rule-based first, LLM review for edge      │ │
│  │  cases. No second LLM needed — pattern      │ │
│  │  matching handles 95%.                      │ │
│  └──────────────────┬──────────────────────────┘ │
│                     ▼                            │
│  ┌─────────────────────────────────────────────┐ │
│  │              EXECUTOR                       │ │
│  │  Runs plan steps with context isolation:    │ │
│  │  - Fresh context per batch                  │ │
│  │  - Intermediate results saved to disk       │ │
│  │  - Tool call JSON repair + retry            │ │
│  │  - Progress tracking                        │ │
│  │                                             │ │
│  │  Uses existing AntBot agent loop            │ │
│  └──────────────────┬──────────────────────────┘ │
│                     ▼                            │
│  ┌─────────────────────────────────────────────┐ │
│  │              TOOLS                          │ │
│  │  File ops │ Shell │ Web │ MCP │ Skills      │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │              WATCHERS (built-in)            │ │
│  │  Heartbeat-based monitoring:                │ │
│  │  - Disk space, Docker containers, services  │ │
│  │  - Alerts via configured channel            │ │
│  │  - Runs inside same process                 │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │              PROVIDERS                      │ │
│  │  Local first:                               │ │
│  │  - LM Studio (localhost:1234)               │ │
│  │  - Exo Cluster (localhost:52415)            │ │
│  │  Cloud fallback (optional, explicit):       │ │
│  │  - Anthropic, OpenAI, etc.                  │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │              MEMORY                         │ │
│  │  Two-layer (from AntBot):                  │ │
│  │  - MEMORY.md (long-term facts)              │ │
│  │  - HISTORY.md (searchable log)              │ │
│  │  Context-aware loading (only load what's    │ │
│  │  relevant to current task)                  │ │
│  └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

## Key Differences from AntBot

| Aspect | NanoBot (upstream) | AntBot |
|---|---|---|
| **LLM target** | Cloud (Claude, GPT-4) | Local first (LM Studio, Exo) |
| **Context strategy** | Dump everything, hope it fits | Measure → Plan → Chunk → Execute |
| **Security** | Allow list per channel | Guard layer reviews tool calls |
| **Monitoring** | HEARTBEAT.md (basic) | Watchers with channel alerts |
| **Provider default** | anthropic/claude-opus | Local endpoint auto-detect |
| **Tool call reliability** | Assumes perfect JSON | JSON repair + retry loop |
| **Memory loading** | Full MEMORY.md every request | Relevant sections only |

## Provider Priority

1. **Auto-detect local**: Check localhost:1234 (LM Studio) and localhost:52415 (Exo) on startup
2. **Use local if available**: Route all requests to local LLM
3. **Cloud only if explicitly configured**: User must opt-in to cloud providers
4. **No silent cloud calls**: Every external API call is logged and visible

## File Structure

```
antbot/
├── __init__.py
├── __main__.py
├── agent/
│   ├── loop.py              # Existing AntBot loop (executor)
│   ├── planner.py           # NEW: Measure + plan before execution
│   ├── guard.py             # NEW: Tool call review layer
│   ├── orchestrator.py      # NEW: Coordinates planner → guard → executor
│   ├── context.py           # Modified: context isolation per batch
│   ├── memory.py            # Modified: selective memory loading
│   ├── skills.py            # Existing
│   ├── subagent.py          # Existing
│   └── tools/               # Existing tool registry
├── providers/
│   ├── local_detect.py      # NEW: Auto-detect LM Studio / Exo
│   ├── litellm_provider.py  # Existing
│   ├── custom_provider.py   # Existing (key for local endpoints)
│   └── ...
├── watchers/                # NEW: Monitoring built into heartbeat
│   ├── __init__.py
│   ├── disk.py              # Disk space monitoring
│   ├── docker.py            # Container health
│   └── service.py           # Process/service checks
├── channels/                # Existing (Telegram, Discord, etc.)
├── bus/                     # Existing message bus
├── config/                  # Existing config system
├── cron/                    # Existing scheduler
├── session/                 # Existing session management
├── skills/                  # Existing skills
├── templates/               # Existing templates
└── utils/
    ├── helpers.py           # Existing
    └── json_repair.py       # NEW: Fix malformed tool call JSON
```

## Planner Detail

The Planner is the key innovation. It sits between the user request and the executor.

### Input
- User message
- Available tools list
- Model context window size (from provider config)

### Process
1. **Measure**: If the task references files/directories, check their sizes
2. **Classify**: Simple (1-3 tool calls) or Complex (4+ steps)
3. **Plan**: For complex tasks, create a step-by-step execution plan
4. **Chunk**: If data exceeds 60% of context window, split into batches

### Output
```json
{
  "type": "simple | chunked",
  "steps": [
    {"action": "list_dir", "target": "/path", "phase": 1},
    {"action": "batch_read", "batch_size": 15, "phase": 2},
    {"action": "summarize", "phase": 2},
    {"action": "merge", "phase": 3}
  ],
  "estimated_batches": 47,
  "context_budget_per_step": 24000
}
```

### Simple tasks bypass planning
"What time is it?" → straight to executor, no planning overhead.

## Guard Detail

Rule-based pattern matching, not a second LLM:

```python
DANGEROUS_PATTERNS = [
    r"rm\s+-rf",
    r"DROP\s+TABLE",
    r"kill\s+-9",
    r"format\s+",
    r"dd\s+if=",
    r">\s*/dev/",
    r"chmod\s+777",
    r"shutdown",
]

SENSITIVE_PATTERNS = [
    r"password",
    r"api.key",
    r"secret",
    r"token",
    r"\.env",
    r"credentials",
    r"private.key",
]
```

When a pattern matches:
1. Log the match
2. Ask user for confirmation via active channel
3. Only proceed with explicit approval

No second LLM needed. 95% of dangerous operations match simple patterns.

## Watchers Detail

Built into the existing heartbeat loop. No separate daemon.

HEARTBEAT.md can include watcher configs:

```markdown
## Watchers

### Disk Space
- Check every: 30min
- Alert when: < 10GB free on any volume
- Alert via: telegram

### Docker
- Check every: 15min
- Monitor: all running containers
- Alert on: unhealthy, restart loop, OOM

### Services
- Check every: 5min
- Monitor: [postgres, redis, nginx]
- Alert on: not running
```

The heartbeat service reads this and runs checks. Alerts go through the normal channel system (Telegram, Discord, etc.).

## Development Phases

### Phase 1: Foundation
- [ ] Rename antbot → antbot throughout codebase
- [ ] Add local provider auto-detection
- [ ] Add JSON repair for tool calls
- [ ] Set local LLM as default provider
- [ ] Basic CLAUDE.md / project setup

### Phase 2: Planner + Guard
- [ ] Implement planner.py (measure + plan)
- [ ] Implement guard.py (pattern-based review)
- [ ] Implement orchestrator.py (coordinate flow)
- [ ] Modify context.py for context isolation
- [ ] Add chunked execution mode to loop.py

### Phase 3: Watchers
- [ ] Disk space watcher
- [ ] Docker container watcher
- [ ] Service/process watcher
- [ ] Alert routing through channels

### Phase 4: Polish
- [ ] Selective memory loading
- [ ] Provider fallback chain
- [ ] CLI improvements
- [ ] Documentation
- [ ] Tests
