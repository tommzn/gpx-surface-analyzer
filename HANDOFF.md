# Handoff: gpx-surface-analyzer

Context document for picking up the work. Summarises the decisions made
and what is still open/untested. For usage and setup see [README.md](README.md).

## Original goal

Analyse GPX cycling routes: what share runs on asphalt, gravel, unpaved
tracks, etc.? Data source: OpenStreetMap via the public Overpass API
(`overpass-api.de`, no API key needed).

## Architecture decisions

- **One shared core module** (`core/surface_analysis.py`), used by both the
  MCP server (`mcp-server/`) and the Claude skill (`claude-skill/`), so the
  matching logic only needs to be maintained in one place.
- **One single Overpass query per route** (bounding box of the entire route
  + 300 m padding), not one query per GPX point — keeps the public server
  load low and makes analysis much faster.
- **MCP SDK API**: uses `mcp.server.mcpserver.MCPServer` (the naming of the
  official Python SDK at development time, `mcp==2.0.0`). If an older SDK is
  present (still `FastMCP`): rename the import/class accordingly, the rest of
  the tool logic stays the same.
- **Transport**: `server.py` selects between `stdio` (default, local) and
  `streamable-http` (Docker/K8s) via the `MCP_TRANSPORT` env var.
- **Deployment target**: private k3s cluster on Raspberry Pi in the home
  network, not publicly reachable. Hence NodePort instead of ingress/TLS,
  `nodeSelector: kubernetes.io/arch: arm64`, `readOnlyRootFilesystem: true`
  with `emptyDir` on `/tmp` as a safety measure.
- **Image distribution**: ghcr.io instead of local import, now automated via
  `.github/workflows/docker-publish.yml` (builds arm64+amd64 via
  buildx/QEMU, pushes on push to `main` or `v*` tags; PRs build only for
  validation, no push).

## Status: Tested

- Core logic (GPX parsing, Haversine, point-to-segment distance,
  grid-index matching, surface classification).
- All three entry points (core module directly, MCP server import,
  skill CLI from an external working directory).
- YAML syntax and field consistency of `k8s/*.yaml` (selector, labels,
  ports, volumes between deployment/service).
- `.skill` package build via `scripts/build_standalone_skill.sh`.
- **Overpass API end-to-end**, against several real GPX routes:
  - Road route (Odelshausen–Dachau, 24 km, 83% asphalt)
  - Bike-park trail (Hohenwart, 33 km, 59% gravel)
  - Narrow rooted singletrack (Tegernbach, 19 km, 49% gravel / 37% unpaved)
  - Longer road tour (69 km, 5,506 points, 63% asphalt)
  - Gravel ride exported from Strava activity data (via Strava MCP,
    `get_activity_streams` → GPX built manually, 68 km, 11,479 points, 86% asphalt)
  - All with `unmatched_percent: 0.0` — 30 m tolerance works well against
    real OSM data in the tested regions (Bavaria).
- **Retry behaviour on transient Overpass errors**: the public server
  responds under load with `429` (rate limit) or occasionally
  `502`/`503`/`504`. `fetch_ways_in_bbox` now retries automatically (up to
  3 attempts, exponential backoff from 5 s, respects `Retry-After` header).
  Verified both against real 429 responses (several routes analysed in quick
  succession) and via a mocked unit test (429×2→success, 404 immediate fail
  without retry, persistent 429 → fail after exhausting all attempts). With a
  very large bounding box (~15×20 km) 3 retries were not enough in one case —
  a further manual attempt was needed. Other errors (e.g. `ConnectionError`
  because the host is unreachable — as in the sandboxed claude.ai environment)
  are intentionally NOT retried.

## Status: NOT tested

- **The GitHub Actions workflow itself** (`docker-publish.yml`) has never
  been verified against a real Actions run — only checked locally for YAML
  syntax and plausibility. Specifically untested: whether the `linux/arm64`
  build via QEMU on `ubuntu-latest` completes in acceptable time, and whether
  `GITHUB_TOKEN` with `packages: write` is actually sufficient to push to the
  repo's own GHCR package (should work according to GitHub docs, but never
  seen live).
- **Local Docker build** (`docker build`/`buildx`) — still never actually
  executed, as Docker was not available in any prior session.
- **k3s deployment** — no real cluster available; manifests only
  YAML-syntactically and field-consistency checked, never run with `kubectl
  apply` against a real cluster.
- **`readOnlyRootFilesystem: true`** — whether this works without issues in
  practice on k3s/containerd is unverified.
- **Installing the `.skill` package in claude.ai** and checking trigger
  recognition of the SKILL.md description in real conversations — only
  structurally validated, never actually triggered.

→ **Recommended next steps:** Watch the first real push to `main` in the
Actions tab to verify the workflow. Then actually deploy the image to a
Pi/k3s and verify the four k3s-related items above before adding more
features.

## Repository structure

```
gpx-surface-analyzer/
├── core/
│   ├── __init__.py
│   └── surface_analysis.py       # sole source of analysis logic (incl. retry/backoff)
├── mcp-server/
│   ├── server.py                  # MCP wrapper (stdio + streamable-http)
│   ├── Dockerfile
│   └── requirements.txt
├── claude-skill/
│   ├── SKILL.md
│   ├── requirements.txt
│   └── scripts/analyze_surface.py # CLI wrapper
├── k8s/
│   ├── deployment.yaml            # NodePort setup, arm64 nodeSelector
│   ├── service.yaml
│   └── kustomization.yaml
├── scripts/
│   └── build_standalone_skill.sh  # builds a self-contained .skill package
├── .github/workflows/
│   └── docker-publish.yml         # builds + pushes image to ghcr.io (main/tags)
├── .dockerignore
├── .gitignore
├── README.md
└── LICENSE (MIT)
```
