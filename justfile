# AntBot — common dev tasks
# Run `just` to see all recipes; `just <recipe>` to execute.

REPO := "48Nauts/AntBot"
FORGEJO_BASE := "http://cosmos.tail138398.ts.net:3000"

default:
    @just --list

# ─── Push / sync ────────────────────────────────────────────────

# Push to both Forgejo (homelab, primary) and GitHub (mirror)
push:
    git push forgejo
    git push origin

# Push only to Forgejo
push-forgejo:
    git push forgejo

# Push only to GitHub
push-github:
    git push origin

# Pull latest from Forgejo (with rebase)
pull:
    git pull --rebase forgejo

# ─── Open in browser ────────────────────────────────────────────

# Open the Forgejo repo
open:
    open "{{FORGEJO_BASE}}/{{REPO}}"

# Open the latest CI runs page
ci:
    open "{{FORGEJO_BASE}}/{{REPO}}/actions"

# Open the issues list
issues:
    open "{{FORGEJO_BASE}}/{{REPO}}/issues"

# Open the pull-requests list
prs:
    open "{{FORGEJO_BASE}}/{{REPO}}/pulls"

# ─── Python: lint / format / test ───────────────────────────────

# Run lint + format checks (no fixes)
lint:
    ruff check .
    ruff format --check .

# Auto-fix lint + reformat
fix:
    ruff check --fix .
    ruff format .

# Run tests
test:
    pytest

# Run tests with coverage report
test-cov:
    pytest --cov=antbot --cov-report=term-missing

# Type check (when ready for it)
typecheck:
    mypy antbot

# ─── Setup ──────────────────────────────────────────────────────

# Bootstrap dev environment (install package + dev deps)
setup:
    pip install -e ".[dev]"

# ─── Docker ─────────────────────────────────────────────────────

# Build the docker image
docker-build:
    docker compose build

# Run the stack
docker-up:
    docker compose up -d

# Tail the logs
docker-logs:
    docker compose logs -f

# Stop the stack
docker-down:
    docker compose down

# ─── Branch helpers ─────────────────────────────────────────────

# Create + switch to a new feature branch (auto-opens tracking issue on push)
feature name:
    git checkout -b feature/{{name}}

# Create + switch to a new fix branch (auto-opens tracking issue on push)
fix-branch name:
    git checkout -b fix/{{name}}

# Create + switch to a new incident branch (auto-opens tracking issue on push)
incident name:
    git checkout -b incident/{{name}}
