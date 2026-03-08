---
name: cleanup
description: Scan and clean disk space waste using the space_ant tool.
always: false
---

# Disk Cleanup

Use the `space_ant` tool to analyze and reclaim disk space.

## Platform Support

**Full support:** macOS (Darwin)
- Xcode caches (iOS DeviceSupport, DerivedData, DocumentationCache)
- Homebrew cache
- macOS system caches (`~/Library/Caches`)

**Cross-platform:** macOS + Linux
- ML model caches (EXO `~/.exo/models`, Hugging Face `~/.cache/huggingface`, Ollama `~/.ollama/models`)
- Docker images, volumes, build cache
- Dev artifacts (`node_modules`, `__pycache__`, `.mypy_cache`, `.tox`, `.next`, `target`)
- Package caches (pip, npm, cargo)
- Temp files (`/tmp`, `/var/tmp`)
- Installer files in Downloads (`.dmg`, `.pkg`, `.iso`)
- System logs (`/var/log`)

## Usage

### Step 1: Always scan first

```
space_ant(action="scan")
```

This produces a categorized report with sizes. Never skip this step.

### Step 2: Review with the user

Present the scan results and let the user decide what to clean. Group items by risk level:

- **Safe** — caches, temp files, dev artifacts (all rebuild on demand)
- **Your call** — ML models, Docker volumes (may contain data the user needs)
- **Don't touch** — anything not in the scan report

### Step 3: Clean (only with explicit confirmation)

```
space_ant(action="clean", confirm=true)
```

The clean action handles:
- Xcode: iOS DeviceSupport, DerivedData, DocumentationCache (macOS)
- Docker: `docker volume prune -f`, `docker image prune -f`
- Homebrew: `brew cleanup` (macOS)
- Ollama: removes `~/.ollama/models` entirely
- Downloads: deletes `.dmg`, `.pkg`, `.iso` installer files
- Temp: clears `/var/tmp`
- Dev waste: `__pycache__`, `.mypy_cache`, `.tox` under project dirs
- Package caches: pip cache, npm cache

**Not cleaned automatically** (too risky):
- EXO models — user should delete via EXO UI or `/model` commands
- Hugging Face models — may be used by other apps (TTS, embeddings)
- Docker containers — may be running
- node_modules — may break active projects

## Tips

- After cleanup, run `scan` again to verify reclaimed space
- For ML model management, use `/model list` to see what's loaded on EXO
- Docker volumes can hold database data — check with `docker volume ls` before pruning
- Xcode iOS DeviceSupport is the single biggest macOS space hog (often 20-40 GB)
