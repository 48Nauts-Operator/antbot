#!/bin/bash
# AntBot Machine Bootstrap — Stage 0
# Run on a fresh Mac to restore from NAS backup.
#
# Usage: curl -sL https://raw.githubusercontent.com/48Nauts-Operator/antbot/main/scripts/bootstrap.sh | bash
#
# This script handles ONLY the prerequisites that the Ansible playbook
# cannot handle itself: Xcode, Homebrew, Ansible, and NAS mount.
# The playbook requires NAS to already be mounted.

set -e

echo "=== AntBot Machine Bootstrap (Stage 0) ==="
echo ""

# 1. Xcode CLI tools
echo "Step 1/6: Xcode CLI tools..."
if ! xcode-select -p &>/dev/null; then
    xcode-select --install
    echo "  Waiting for Xcode CLI tools installation..."
    echo "  Press Enter when done."
    read -r
else
    echo "  Already installed."
fi

# 2. Homebrew
echo "Step 2/6: Homebrew..."
if ! command -v brew &>/dev/null; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
else
    echo "  Already installed."
fi

# 3. Ansible + Python
echo "Step 3/6: Ansible + Python..."
brew install ansible python@3.12 2>/dev/null || true

# 4. Mount NAS
echo "Step 4/6: Mount NAS..."
NAS_BACKUP="/Volumes/Tron/mpb_backup"

if [ -d "$NAS_BACKUP/Machines" ]; then
    echo "  NAS already mounted at $NAS_BACKUP"
else
    read -p "  NAS address [nas.local]: " NAS_ADDR
    NAS_ADDR=${NAS_ADDR:-nas.local}

    mkdir -p /Volumes/Tron 2>/dev/null || true
    mount -t smbfs "//${NAS_ADDR}/Tron" /Volumes/Tron 2>/dev/null || {
        read -sp "  NAS password: " NAS_PASS
        echo ""
        mount -t smbfs "//guest:${NAS_PASS}@${NAS_ADDR}/Tron" /Volumes/Tron
    }

    if [ ! -d "$NAS_BACKUP/Machines" ]; then
        echo "  ERROR: NAS mounted but $NAS_BACKUP/Machines not found."
        echo "  Is this the correct share? Aborting."
        exit 1
    fi
    echo "  NAS mounted and verified."
fi

# 5. Select machine profile
echo "Step 5/6: Select machine profile..."
HOSTNAME=$(hostname -s | tr '[:upper:]' '[:lower:]')
PLAYBOOK="$NAS_BACKUP/Machines/${HOSTNAME}/playbook.yml"

if [ -f "$PLAYBOOK" ]; then
    echo "  Found playbook for ${HOSTNAME}"
else
    echo "  No playbook for ${HOSTNAME}. Available profiles:"
    ls "$NAS_BACKUP/Machines/" 2>/dev/null || echo "  (none)"
    read -p "  Use profile (or 'new' to skip): " PROFILE
    if [ "$PROFILE" = "new" ] || [ -z "$PROFILE" ]; then
        echo ""
        echo "  Starting with minimal setup."
        echo "  Install AntBot: pip3 install -e /path/to/antbot"
        echo "  Generate manifest: antbot backup --manifest"
        echo "  AntBot will learn this machine over time."
        exit 0
    fi
    PLAYBOOK="$NAS_BACKUP/Machines/${PROFILE}/playbook.yml"
    if [ ! -f "$PLAYBOOK" ]; then
        echo "  ERROR: Playbook not found: $PLAYBOOK"
        exit 1
    fi
fi

# 6. Run playbook
echo "Step 6/6: Running Ansible playbook..."
echo ""
ansible-playbook "$PLAYBOOK"

echo ""
echo "=== Stage 1 complete: Foundation restored ==="
echo ""
echo "Next steps:"
echo "  1. Restore SSH private keys: antbot restore-keys"
echo "  2. Verify: antbot backup --manifest --dry-run"
echo "  3. Start scout: antbot scout"
echo ""
echo "=== Bootstrap complete ==="
