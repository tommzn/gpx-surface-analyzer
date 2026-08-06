#!/usr/bin/env python3
"""
GPX Surface Analyzer - Claude Skill CLI
==========================================

Thin CLI wrapper around the shared analysis logic in
core/surface_analysis.py. See there for the actual implementation
(GPX parsing, Overpass query, matching).

Usage:
    python3 analyze_surface.py <path-to-route.gpx>
    python3 analyze_surface.py <path-to-route.gpx> --output result.json
"""

import argparse
import json
import sys
from pathlib import Path

# Add the scripts/ directory to the path so the sibling "core" package
# can be imported regardless of where the script is invoked from.
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from core.surface_analysis import analyze_gpx_surface
except ImportError as e:
    print(
        f"Missing package or core module not found: {e}\n"
        f"Please install dependencies with:\n"
        f"  pip install -r requirements.txt --break-system-packages",
        file=sys.stderr,
    )
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Analyse road surfaces of a GPX route.")
    parser.add_argument("gpx_path", help="Path to the .gpx file")
    parser.add_argument("--output", "-o", help="Optional: save result as a JSON file")
    args = parser.parse_args()

    with open(args.gpx_path, "r", encoding="utf-8") as f:
        gpx_text = f.read()

    result = analyze_gpx_surface(gpx_text)
    output_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"Result saved to {args.output}")
    else:
        print(output_json)

    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
