# Image du serveur MCP VMware (stdio).
# Build : docker build -t mcp-vmware -f Containerfile .
# Run   : docker run -i --rm --env-file .vcenter.env mcp-vmware
# Compatible docker et podman.

FROM python:3.12-slim

LABEL org.opencontainers.image.title="mcp-vmware" \
      org.opencontainers.image.description="MCP server to pilot VMware vCenter (role-based access)" \
      org.opencontainers.image.licenses="MIT"

# Build derriere un proxy d'entreprise avec interception TLS :
#   docker build --network=host \
#     --build-arg http_proxy --build-arg https_proxy --build-arg no_proxy \
#     --build-arg PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org" \
#     -t mcp-vmware -f Containerfile .
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home mcp

USER mcp

# Configuration par variables d'environnement :
#   VC_HOST, VC_USER, VC_PASS      (obligatoires)
#   MCP_VMWARE_ROLE                (viewer|operator|vm_admin|infra_admin, defaut viewer)
# ou par fichier monte : -v ./.vcenter.env:/config/.vcenter.env:ro
#   avec MCP_VMWARE_ENV_FILE=/config/.vcenter.env
ENTRYPOINT ["python", "-m", "mcp_vmware"]
