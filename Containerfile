# VMware MCP server image (stdio).
# Build: docker build -t mcp-vmware -f Containerfile .
# Run:   docker run -i --rm --env-file .vcenter.env mcp-vmware
# Works with docker and podman.

FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

LABEL org.opencontainers.image.title="mcp-vmware" \
      org.opencontainers.image.description="MCP server to pilot VMware vCenter (role-based access)" \
      org.opencontainers.image.licenses="MIT"

# Build behind a corporate proxy with TLS interception:
#   docker build --network=host \
#     --build-arg http_proxy --build-arg https_proxy --build-arg no_proxy \
#     --build-arg PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org" \
#     -t mcp-vmware -f Containerfile .
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=

WORKDIR /app
COPY pyproject.toml requirements-container.txt ./
COPY src ./src
RUN pip install --no-cache-dir --require-hashes -r requirements-container.txt \
 && pip install --no-cache-dir --no-deps --no-build-isolation . \
 && useradd --create-home mcp

USER mcp

# Configuration via environment variables:
#   VC_HOST, VC_USER, VC_PASS      (required)
#   MCP_VMWARE_ROLE                (viewer|operator|vm_admin|infra_admin, default viewer)
# or via a mounted file: -v ./.vcenter.env:/config/.vcenter.env:ro
#   with MCP_VMWARE_ENV_FILE=/config/.vcenter.env
ENTRYPOINT ["python", "-m", "mcp_vmware"]
