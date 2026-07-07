#!/usr/bin/env bash
# Deploie mcp-vmware sur la machine rebond jumphost (~/VMware/mcp-vmware)
# et installe les dependances dans le venv Python 3.12.
set -euo pipefail

REMOTE="jumphost"
REMOTE_DIR="VMware/mcp-vmware"

cd "$(dirname "$0")"

echo "== rsync du code vers $REMOTE:~/$REMOTE_DIR =="
rsync -a --delete \
  --exclude '__pycache__' --exclude '*.egg-info' --exclude '.git' \
  src pyproject.toml run.sh tools "$REMOTE:$REMOTE_DIR/"

echo "== installation dans le venv =="
ssh "$REMOTE" "chmod +x ~/$REMOTE_DIR/run.sh && ~/VMware/venv/bin/pip install -q -e ~/$REMOTE_DIR && ~/VMware/venv/bin/python -c 'import mcp_vmware; print(\"mcp_vmware\", mcp_vmware.__version__, \"installe\")'"

echo "== OK =="
