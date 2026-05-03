#!/usr/bin/env bash
#
# AntBot installer — one-line install for macOS (Linux support TBD).
#
# Usage:
#   curl -fsSL https://github.com/48Nauts-Operator/antbot/raw/main/install.sh | bash
#
#   # Or with options:
#   curl -fsSL ... | INSTALL_DIR=~/projects/antbot bash
#
# Environment variables:
#   ANTBOT_REPO     — git remote (default: GitHub origin)
#   ANTBOT_BRANCH   — branch to install from (default: main)
#   INSTALL_DIR     — where to clone (default: ~/Developer/antbot)
#   ANTBOT_HOME     — runtime data + binary path (default: ~/.antbot)
#   SKIP_DEPS=1     — skip brew install of system deps (advanced)
#

set -euo pipefail

# ─── config ──────────────────────────────────────────────────────────
ANTBOT_REPO="${ANTBOT_REPO:-https://github.com/48Nauts-Operator/antbot.git}"
ANTBOT_BRANCH="${ANTBOT_BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/Developer/antbot}"
ANTBOT_HOME="${ANTBOT_HOME:-$HOME/.antbot}"

# ─── output helpers ──────────────────────────────────────────────────
bold()   { printf "\033[1m%s\033[0m\n" "$1"; }
info()   { printf "\033[34m→\033[0m %s\n" "$1"; }
ok()     { printf "\033[32m✓\033[0m %s\n" "$1"; }
warn()   { printf "\033[33m!\033[0m %s\n" "$1" >&2; }
err()    { printf "\033[31m✗\033[0m %s\n" "$1" >&2; }
section(){ printf "\n\033[1;34m═══ %s ═══\033[0m\n" "$1"; }

# ─── platform check ──────────────────────────────────────────────────
case "$(uname -s)" in
    Darwin) ;;
    *) err "Only macOS is supported right now. Linux/Windows: PRs welcome."; exit 1 ;;
esac

# ─── prerequisite: brew ──────────────────────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
    err "Homebrew is required. Install it first:"
    echo '   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
fi

# ─── 1. system dependencies ──────────────────────────────────────────
section "Step 1/5 — Installing system dependencies"

if [ "${SKIP_DEPS:-0}" = "1" ]; then
    warn "SKIP_DEPS=1 → skipping brew installs (you must have go, protobuf, uv installed manually)"
else
    NEEDED=()
    for pkg in go protobuf uv; do
        if brew list --formula "$pkg" >/dev/null 2>&1; then
            ok "$pkg already installed"
        else
            NEEDED+=("$pkg")
        fi
    done
    if [ ${#NEEDED[@]} -gt 0 ]; then
        info "Installing: ${NEEDED[*]}"
        brew install "${NEEDED[@]}"
    fi
fi

# ─── 2. Go protoc plugins ────────────────────────────────────────────
section "Step 2/5 — Installing Go protobuf plugins"

if ! command -v protoc-gen-go >/dev/null 2>&1; then
    info "Installing protoc-gen-go..."
    go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
fi
if ! command -v protoc-gen-go-grpc >/dev/null 2>&1; then
    info "Installing protoc-gen-go-grpc..."
    go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
fi
ok "Go plugins ready"

# Add ~/go/bin to PATH for the rest of this script
export PATH="$HOME/go/bin:$PATH"

# Persist in shell rc if missing
RC=""
[ -n "${ZSH_VERSION:-}" ] && RC="$HOME/.zshrc"
[ -z "$RC" ] && [ -f "$HOME/.zshrc" ] && RC="$HOME/.zshrc"
[ -z "$RC" ] && [ -f "$HOME/.bashrc" ] && RC="$HOME/.bashrc"
if [ -n "$RC" ] && ! grep -q '$HOME/go/bin' "$RC" 2>/dev/null; then
    echo '' >> "$RC"
    echo '# Added by AntBot installer' >> "$RC"
    echo 'export PATH="$HOME/go/bin:$PATH"' >> "$RC"
    ok "Added \$HOME/go/bin to PATH in $RC"
fi

# ─── 3. clone or update the repo ─────────────────────────────────────
section "Step 3/5 — Cloning AntBot"

mkdir -p "$(dirname "$INSTALL_DIR")"

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Repo exists at $INSTALL_DIR — pulling latest..."
    git -C "$INSTALL_DIR" fetch origin
    git -C "$INSTALL_DIR" checkout "$ANTBOT_BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only
elif [ -d "$INSTALL_DIR" ]; then
    err "$INSTALL_DIR exists but is not a git repo. Move it aside or set INSTALL_DIR=<other-path> and retry."
    exit 1
else
    info "Cloning into $INSTALL_DIR..."
    git clone --branch "$ANTBOT_BRANCH" "$ANTBOT_REPO" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
ok "Source ready at $INSTALL_DIR"

# ─── 4. Python install ───────────────────────────────────────────────
section "Step 4/5 — Setting up Python environment"

if [ ! -d ".venv" ]; then
    info "Creating Python 3.11 venv (uv will download Python if needed)..."
    uv venv --python 3.11
fi

# shellcheck disable=SC1091
source .venv/bin/activate

info "Installing Python package + dev deps..."
uv pip install -e ".[dev]"
ok "Python install complete"

# ─── 5. Build the Go exec binary ─────────────────────────────────────
section "Step 5/5 — Building the Go exec binary"

mkdir -p "$ANTBOT_HOME/bin"
cd antbot-exec
make build
make install     # copies to ~/.antbot/bin/
cd ..
ok "Go binary installed → $ANTBOT_HOME/bin/antbot-exec"

# ─── done ────────────────────────────────────────────────────────────
section "✓ Install complete"

cat <<EOF

  ${INSTALL_DIR}/.venv/bin/antbot   ← the CLI
  ${ANTBOT_HOME}/bin/antbot-exec    ← the Go file-ops daemon

To use it in this shell right now:

  cd ${INSTALL_DIR}
  source .venv/bin/activate
  antbot onboard            # interactive config
  antbot agent              # start chat

To make 'antbot' available in any new terminal, add this to your shell rc:

  alias antbot="${INSTALL_DIR}/.venv/bin/antbot"

  # or activate the venv each time:
  source ${INSTALL_DIR}/.venv/bin/activate

Optional extras:
  • Matrix bot with E2E:   uv pip install -e ".[matrix]"   (needs: brew install libolm cmake)

Docs: ${INSTALL_DIR}/README.md

EOF
