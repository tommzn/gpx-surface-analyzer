---
name: gpx-surface-analysis
description: Analyses a GPX cycling route and computes the percentage breakdown of road surface types (asphalt, gravel, unpaved, cobblestone) using OpenStreetMap data. Use this whenever the user asks about the surface composition, gravel/asphalt ratio, "what percentage is gravel/unpaved", or the road conditions of an uploaded or referenced .gpx file — even if they just say "analyse my route" or "what's the terrain like" without explicitly mentioning "surface".
---

# GPX Surface Analysis

Calculates what share of a ridden (or planned) cycling route runs on
asphalt, gravel, unpaved tracks, etc. Data source is OpenStreetMap via
the public Overpass API (no API key needed).

The actual analysis logic lives in `../core/surface_analysis.py` (part of
the `gpx-surface-analyzer` repo) and is also used by the MCP server in the
same repo. This skill script is just a CLI wrapper around it.

## When this skill applies

- User uploads a `.gpx` file and asks about surface type / road conditions
- User asks "what % of my Strava ride was gravel/unpaved/asphalt"
- User wants to compare multiple routes by surface composition

## Prerequisite: internet access

The script needs outbound HTTPS access to `overpass-api.de`. In the
sandboxed execution environment of Claude.ai (claude.ai chat with code
execution) that host is **not** on the network allowlist — the script will
fail with a connection error there. It works reliably in environments with
unrestricted internet access, e.g.:

- **Claude Code** (running locally on the user's machine)
- **Claude Cowork** (if network access is permitted there)

If an execution fails with "Connection refused" or similar, tell the user
directly that it is due to network restrictions in the current environment,
rather than retrying multiple times.

## Prerequisite: repo structure

This script imports `core.surface_analysis` relative to the repo root
(two levels above `scripts/`). It must therefore be inside the cloned
`gpx-surface-analyzer` repo, not copied out in isolation.

## Procedure

1. **Ensure dependencies** (once, if not already installed):
   ```bash
   pip install -r <repo-root>/claude-skill/requirements.txt --break-system-packages
   ```

2. **Run the script** with the path to the GPX file:
   ```bash
   python3 <repo-root>/claude-skill/scripts/analyze_surface.py /path/to/route.gpx
   ```
   Optionally write the result directly to a file:
   ```bash
   python3 <repo-root>/claude-skill/scripts/analyze_surface.py /path/to/route.gpx --output result.json
   ```

3. **Interpret the result and summarise for the user.** The script returns
   JSON, e.g.:
   ```json
   {
     "total_distance_km": 42.7,
     "matched_distance_km": 41.9,
     "surface_percentages": {
       "asphalt": 68.4,
       "gravel": 24.1,
       "unpaved": 5.2,
       "cobblestone": 2.3
     },
     "unmatched_percent": 1.9
   }
   ```
   Don't just output the raw JSON — put the numbers into plain language
   (e.g. "Your route was about two thirds asphalt, with nearly a quarter
   gravel").

## How it works (background, for follow-up questions)

- A single Overpass query fetches all `highway=*` ways within the bounding
  box of the entire route (rather than one query per GPX point — keeps the
  public server load low and is significantly faster).
- Each route segment is matched to the nearest OSM way via
  point-to-line-segment distance (tolerance: 30 m).
- If the `surface` tag is missing in OSM, the `highway` tag is used as a
  rough fallback (e.g. `track` → gravel, `cycleway` → asphalt). This is an
  approximation, not a guarantee — be transparent about this if the user
  asks about accuracy.
- `unmatched_percent` shows the share that could not be matched to any OSM
  way (e.g. off mapped tracks or gaps in OSM data).

## Limitations

- Very long routes (>150 km) produce larger Overpass responses and slightly
  longer run times, but remain manageable in principle.
- For inaccurate GPS tracks (e.g. dense forest) the 30 m tolerance in
  `core/surface_analysis.py` (constant `MAX_MATCH_DISTANCE_M`) can be
  increased if needed.

## Distributing as a standalone .skill package

For installation via the Claude skill card (independent of the repo),
`core/surface_analysis.py` must be copied into the skill folder, as a
`.skill` package must be self-contained. See
`scripts/build_standalone_skill.sh` in the repo root for this.
