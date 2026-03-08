# AntBot - Privacy-First Personal AI Agent

## Project Overview
AntBot is a privacy-first personal AI agent forked from NanoBot, rebuilt to run entirely on local LLMs (LM Studio, Exo). The key innovation is a Planner layer that measures, plans, and chunks tasks so they work within small model context windows.

## Repository
- **Origin**: github.com:48Nauts-Operator/antbot.git
- **Upstream**: github.com/HKUDS/nanobot (MIT license)
- **License**: MIT (open-source)

## Architecture
See ARCHITECTURE.md for full details.

Core flow: User Request → Planner (measure + plan) → Guard (review) → Executor (chunked) → Response

### Key Components
- **Planner**: Scopes tasks, creates execution plans, chunks large jobs
- **Guard**: Pattern-based tool call review (no second LLM needed)
- **Executor**: Runs plan steps with context isolation per batch
- **Watchers**: Built-in monitoring via heartbeat (disk, docker, services)
- **Providers**: Local LLM first (auto-detect LM Studio/Exo), cloud opt-in only

## Development Guidelines
- Local LLM is always the default — never send data to cloud without explicit config
- Keep context small — every LLM call should use minimum necessary context
- No separate daemons — monitoring runs inside the same process via heartbeat
- Test with 8B models first — if it works on Qwen3-8B, it works everywhere
- Guard uses pattern matching, not a second LLM call

## Tech Stack
- Python 3.11+
- LiteLLM for provider routing
- OpenAI-compatible API for local LLMs
- Existing AntBot channel system (Telegram, Discord, CLI, etc.)

## File Structure
```
antbot/              # Core source (renamed from antbot/)
├── agent/
│   ├── planner.py       # NEW: Measure + plan
│   ├── guard.py         # NEW: Tool call review
│   ├── orchestrator.py  # NEW: Coordinates flow
│   ├── loop.py          # Executor (from AntBot)
│   ├── context.py       # Modified for context isolation
│   └── tools/           # Tool registry
├── providers/
│   ├── local_detect.py  # NEW: Auto-detect local LLMs
│   └── ...              # Existing providers
├── watchers/            # NEW: Monitoring
├── channels/            # Existing channels
└── ...
```
