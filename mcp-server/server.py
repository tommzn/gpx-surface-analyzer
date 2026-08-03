"""
GPX Surface Analyzer - MCP Server
===================================

Duenner MCP-Wrapper um die gemeinsame Analyse-Logik in
core/surface_analysis.py. Siehe dort fuer die eigentliche
Implementierung (GPX-Parsing, Overpass-Abfrage, Matching).
"""

import os
import sys
from pathlib import Path

# Repo-Root zum Pfad hinzufuegen, damit "core" importierbar ist,
# unabhaengig davon von wo aus der Server gestartet wird.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.surface_analysis import analyze_gpx_surface as _analyze_gpx_surface  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

server = MCPServer("gpx-surface-analyzer")


@server.tool()
def analyze_gpx_surface(gpx_content: str) -> dict:
    """
    Analysiert eine GPX-Route und berechnet den prozentualen Anteil
    verschiedener Wegoberflaechen (Asphalt, Schotter, unbefestigt, ...)
    basierend auf OpenStreetMap-Daten.

    Args:
        gpx_content: Der vollstaendige Inhalt einer GPX-Datei als String
                      (z.B. per Datei-Upload gelesen und hier eingefuegt).

    Returns:
        Dict mit:
        - total_distance_km: Gesamtstrecke der Route
        - matched_distance_km: Strecke, die einem OSM-Weg zugeordnet werden konnte
        - surface_percentages: {kategorie: prozent} ueber die Gesamtstrecke
        - unmatched_percent: Anteil ohne Zuordnung (z.B. abseits von OSM-Wegen)
    """
    return _analyze_gpx_surface(gpx_content)


@server.tool()
def analyze_gpx_file(gpx_path: str) -> dict:
    """
    Wie analyze_gpx_surface, liest die GPX-Datei aber direkt vom
    Dateisystem des MCP-Servers ein.

    Args:
        gpx_path: Absoluter Pfad zur .gpx-Datei auf dem Rechner, auf dem
                   dieser MCP-Server laeuft.
    """
    try:
        with open(gpx_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return {"error": f"Datei konnte nicht gelesen werden: {e}"}
    return _analyze_gpx_surface(content)


if __name__ == "__main__":
    # Lokal (Claude Desktop/Code): stdio, kein Netzwerk-Port noetig -> Default.
    # Containerisiert (Docker/K8s): MCP_TRANSPORT=streamable-http setzen,
    # damit der Server unter MCP_HOST:MCP_PORT per HTTP erreichbar ist.
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(
            transport=transport,  # "streamable-http" oder "sse"
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8000")),
        )
