#!/usr/bin/env python3
"""
GPX Surface Analyzer - Claude-Skill CLI
==========================================

Duenner CLI-Wrapper um die gemeinsame Analyse-Logik in
core/surface_analysis.py. Siehe dort fuer die eigentliche
Implementierung (GPX-Parsing, Overpass-Abfrage, Matching).

Nutzung:
    python3 analyze_surface.py <pfad-zur-route.gpx>
    python3 analyze_surface.py <pfad-zur-route.gpx> --output ergebnis.json
"""

import argparse
import json
import sys
from pathlib import Path

# Repo-Root zum Pfad hinzufuegen, damit "core" importierbar ist,
# unabhaengig davon von wo aus das Skript aufgerufen wird.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from core.surface_analysis import analyze_gpx_surface
except ImportError as e:
    print(
        f"Fehlendes Paket oder core-Modul nicht gefunden: {e}\n"
        f"Bitte Abhaengigkeiten installieren mit:\n"
        f"  pip install -r requirements.txt --break-system-packages\n"
        f"und sicherstellen, dass dieses Skript innerhalb des geklonten "
        f"gpx-surface-analyzer-Repos liegt (core/ muss zwei Ebenen ueber "
        f"scripts/ liegen).",
        file=sys.stderr,
    )
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Analysiert Wegoberflaechen einer GPX-Route.")
    parser.add_argument("gpx_path", help="Pfad zur .gpx-Datei")
    parser.add_argument("--output", "-o", help="Optional: Ergebnis als JSON-Datei speichern")
    args = parser.parse_args()

    with open(args.gpx_path, "r", encoding="utf-8") as f:
        gpx_text = f.read()

    result = analyze_gpx_surface(gpx_text)
    output_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"Ergebnis gespeichert in {args.output}")
    else:
        print(output_json)

    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
