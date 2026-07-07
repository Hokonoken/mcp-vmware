#!/usr/bin/env bash
# Deploys mcp-vmware to the jumphost machine (~/VMware/mcp-vmware)
# and installs the dependencies into the Python 3.12 venv.
set -euo pipefail

REMOTE="jumphost"
REMOTE_DIR="VMware/mcp-vmware"

cd "$(dirname "$0")"

echo "== rsync code to $REMOTE:~/$REMOTE_DIR =="
rsync -a --delete \
  --exclude '__pycache__' --exclude '*.egg-info' --exclude '.git' \
  src pyproject.toml run.sh tools "$REMOTE:$REMOTE_DIR/"

echo "== installing into the venv =="
ssh "$REMOTE" "chmod +x ~/$REMOTE_DIR/run.sh && ~/VMware/venv/bin/pip install -q -e ~/$REMOTE_DIR && ~/VMware/venv/bin/python -c 'import mcp_vmware; print(\"mcp_vmware\", mcp_vmware.__version__, \"installed\")'"

echo "== OK =="
