# gpx-surface-analyzer MCP Server
#
# Build-Kontext muss das Repo-ROOT sein (nicht mcp-server/), da core/
# mitkopiert werden muss:
#   docker build -f mcp-server/Dockerfile -t gpx-surface-mcp:latest .
#
# Standard-Transport im Container ist streamable-http (fuer Docker/K8s
# sinnvoll). Fuer stdio-Nutzung via "docker run -i" MCP_TRANSPORT=stdio
# setzen (siehe README).

FROM python:3.12-slim AS base

# Kein Bytecode-Cache in Image, unbuffered Logs fuer saubere Container-Logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Nur requirements zuerst kopieren -> Docker-Layer-Cache greift bei
# Code-Aenderungen, ohne dass Dependencies neu installiert werden muessen
COPY mcp-server/requirements.txt ./mcp-server/requirements.txt
RUN pip install --no-cache-dir -r mcp-server/requirements.txt

# Jetzt den eigentlichen Code kopieren (core/ + mcp-server/)
COPY core/ ./core/
COPY mcp-server/server.py ./mcp-server/server.py

# Nicht als root laufen
RUN useradd --create-home --uid 1000 mcpuser
USER mcpuser

ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

EXPOSE 8000

CMD ["python3", "mcp-server/server.py"]
