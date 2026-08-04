"""
GPX Surface Analyzer - MCP Server
===================================

Thin MCP wrapper around the shared analysis logic in
core/surface_analysis.py. See there for the actual implementation
(GPX parsing, Overpass query, matching).
"""

import os
import sys
from pathlib import Path

# Add the repo root to the path so "core" can be imported regardless of
# where the server is started from.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.surface_analysis import analyze_gpx_surface as _analyze_gpx_surface  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

server = MCPServer("gpx-surface-analyzer")


@server.tool()
def analyze_gpx_surface(gpx_content: str) -> dict:
    """
    Analyse a GPX route and compute the percentage breakdown of road surface
    types (asphalt, gravel, unpaved, ...) based on OpenStreetMap data.

    Args:
        gpx_content: Full content of a GPX file as a string
                     (e.g. read from an uploaded file and passed in here).

    Returns:
        Dict with:
        - total_distance_km: total route distance
        - matched_distance_km: distance that could be matched to an OSM way
        - surface_percentages: {category: percent} over the total distance
        - unmatched_percent: share that could not be matched (e.g. off mapped ways)
    """
    return _analyze_gpx_surface(gpx_content)


@server.tool()
def analyze_gpx_file(gpx_path: str) -> dict:
    """
    Like analyze_gpx_surface, but reads the GPX file directly from the
    filesystem of the machine running this MCP server.

    Args:
        gpx_path: Absolute path to the .gpx file on the server machine.
    """
    try:
        with open(gpx_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return {"error": f"Could not read file: {e}"}
    return _analyze_gpx_surface(content)


if __name__ == "__main__":
    # Local (Claude Desktop/Code): stdio, no network port needed -> default.
    # Containerised (Docker/K8s): set MCP_TRANSPORT=streamable-http so the
    # server is reachable via HTTP at MCP_HOST:MCP_PORT.
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(
            transport=transport,  # "streamable-http" or "sse"
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8000")),
        )
