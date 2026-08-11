# gpx-surface-analyzer

> **This repository has been archived.**
> The Claude skill and MCP server have moved to [tommzn/ai-toolkit](https://github.com/tommzn/ai-toolkit):
> - Skill → [`skills/gpx-surface-analyzer/`](https://github.com/tommzn/ai-toolkit/tree/main/skills/gpx-surface-analyzer)
> - MCP server → [`mcp/gpx-surface-analyzer/`](https://github.com/tommzn/ai-toolkit/tree/main/mcp/gpx-surface-analyzer)



Analyses GPX cycling routes and computes the percentage breakdown of road
surface types (asphalt, gravel, unpaved, cobblestone) using OpenStreetMap
data via the public Overpass API.

Two ways to use it, one shared core:

- **`mcp-server/`** – MCP server for Claude Desktop / Claude Code, exposes
  the analysis as tools (`analyze_gpx_surface`, `analyze_gpx_file`)
- **`claude-skill/`** – Claude Skill (SKILL.md + script) that Claude runs
  autonomously when a user asks about the surface composition of an uploaded
  GPX route

Both use `core/surface_analysis.py` — the actual logic (GPX parsing,
Overpass query, matching, classification) lives in exactly one place.

## How it works

1. Parse GPX → extract track points
2. Compute bounding box of the entire route (+ padding)
3. **One single** Overpass query fetches all ways (`highway=*`) in that box
   including geometry and `surface` tag — deliberately not one query per
   point, to be kind to the public server and keep analysis fast
4. Each route segment is matched to the nearest OSM way via
   point-to-line-segment distance (tolerance: 30 m, accelerated with a grid
   index)
5. Segment lengths are summed per surface category and returned as
   percentages of the total distance

No API key required — Overpass is publicly accessible (see
[dev.overpass-api.de](https://dev.overpass-api.de) for fair-use guidelines).
The public server occasionally responds with `429` (rate limit) or
`502`/`503`/`504` (timeout/overload) under load — the query
(`fetch_ways_in_bbox` in `core/surface_analysis.py`) retries such transient
errors automatically with exponential backoff (up to 3 attempts, wait time
doubles each time, honours a `Retry-After` header if present). Other errors
(e.g. unreachable host) are intentionally not retried, as retrying won't
help.

## Repository structure

```
gpx-surface-analyzer/
├── core/
│   ├── __init__.py
│   └── surface_analysis.py       # shared core logic (single source of truth)
├── mcp-server/
│   ├── server.py                  # MCP wrapper, imports core/ (stdio + streamable-http)
│   ├── Dockerfile
│   └── requirements.txt
├── claude-skill/
│   ├── SKILL.md
│   ├── requirements.txt
│   └── scripts/
│       └── analyze_surface.py     # CLI wrapper, imports core/
├── k8s/
│   ├── deployment.yaml            # NodePort setup for private home network, arm64 nodeSelector
│   ├── service.yaml
│   └── kustomization.yaml
├── scripts/
│   └── build_standalone_skill.sh  # builds a self-contained .skill package
├── .github/
│   └── workflows/
│       └── docker-publish.yml     # builds mcp-server image (arm64+amd64), pushes to ghcr.io on main/tags
├── .dockerignore
└── README.md
```

## Using the MCP server

```bash
cd mcp-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

In `claude_desktop_config.json` (or the MCP config for Claude Code):

```json
{
  "mcpServers": {
    "gpx-surface-analyzer": {
      "command": "/absolute/path/to/gpx-surface-analyzer/mcp-server/venv/bin/python3",
      "args": ["/absolute/path/to/gpx-surface-analyzer/mcp-server/server.py"]
    }
  }
}
```

### Containerised (Docker / Kubernetes)

For local stdio use (Claude Desktop/Code) you do **not** need Docker/K8s —
that only makes sense when you want the server to run persistently and be
reachable over HTTP. The server supports the `streamable-http` transport in
addition to stdio for that purpose.

The instructions below are tailored to a **private home-network cluster on
Raspberry Pi (k3s), not publicly reachable** — access only from the local
LAN via NodePort, no ingress/TLS needed.

**1. Build the image and push to ghcr.io**

This happens automatically via `.github/workflows/docker-publish.yml`: on
every push to `main` that touches `core/` or `mcp-server/`, and on version
tags (`v*`), GitHub Actions builds the image for `linux/arm64` *and*
`linux/amd64` and pushes it to
`ghcr.io/<github-user>/gpx-surface-mcp:latest` (also tagged with the short
SHA, or the version number for tagged releases). On pull requests the image
is built but not pushed (validation without publishing). No manual step
needed — just `git push` and watch the run in the Actions tab. The first
GHCR package created is **private** by default; the GitHub Actions token
(`GITHUB_TOKEN`) automatically has push access, but for pulling on the Pi
nodes see the pull secret note below.

You can still build and push manually for fast local iterations without
waiting for CI. Raspberry Pi runs arm64 (64-bit OS — verify with `uname -m`
on the Pi, should show `aarch64`). Building from an Apple Silicon Mac
(e.g. Mac Mini M1) works natively without emulation:

```bash
docker buildx build \
  --platform linux/arm64 \
  -f mcp-server/Dockerfile \
  -t ghcr.io/<your-github-user>/gpx-surface-mcp:latest \
  --push .
```

From an x86 machine `buildx` needs QEMU emulation (noticeably slower, but
works identically with the same command).

If the ghcr.io package remains **private**, the Pis need a pull secret
(create once):
```bash
kubectl create secret docker-registry ghcr-pull-secret \
  --docker-server=ghcr.io \
  --docker-username=<your-github-user> \
  --docker-password=<github-PAT-with-read:packages-scope> \
  --docker-email=<your-email>
```
and enable the commented-out `imagePullSecrets` block in
`k8s/deployment.yaml`. Alternatively, set the package to "Public" in the
GitHub Package settings — then no secret is needed at all.

**2. Deploy to k3s**

Update `image:` in `k8s/deployment.yaml` to point to your pushed image, then:
```bash
kubectl apply -k k8s/
kubectl get pods -w
```

**3. Test connectivity**

The service is exposed as a `NodePort` on port `30800` — reachable via the
IP of **any** node in the cluster (even if the pod runs on just one, k3s
routes automatically):
```bash
curl -i http://<ip-of-any-pi>:30800/mcp
```
Then add `http://<pi-ip>:30800/mcp` as a remote MCP endpoint in the
Claude Code config on your Mac.

**Test locally with Docker before deploying to the Pis:**
```bash
docker build -f mcp-server/Dockerfile -t gpx-surface-mcp:latest .
docker run --rm -p 8000:8000 gpx-surface-mcp:latest
# MCP endpoint: http://localhost:8000/mcp
```

> **Egress note:** The server needs outbound HTTPS access to
> `overpass-api.de`. k3s has no restrictive egress `NetworkPolicy` by
> default — in a home-network setup this is normally a non-issue as long as
> your router/firewall allows outbound HTTPS.

## Using the Claude Skill

Run directly from the repo (the script imports `core/` relatively):

```bash
pip install -r claude-skill/requirements.txt --break-system-packages
python3 claude-skill/scripts/analyze_surface.py /path/to/route.gpx
```

To install as a standalone `.skill` package (independent of the repo, e.g.
via the "Save skill" card in Claude.ai), `core/` must be bundled in:

```bash
./scripts/build_standalone_skill.sh ./dist
```

Produces `dist/gpx-surface-analysis.skill`.

> **Network note:** The skill needs access to `overpass-api.de`. In the
> sandboxed code-execution environment of claude.ai that host is not on the
> allowlist — the skill will fail with a connection error there. It works
> reliably in Claude Code (local) or any other environment with unrestricted
> internet access.

## Example output

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

## Limitations

- Very long routes (>150 km) or routes with a large bounding box (>~15 km
  edge length) produce larger Overpass responses and can occasionally time
  out even with automatic retries when the public server is under heavy load
  — a manual retry usually helps in that case.
- If the `surface` tag is missing in OSM, the `highway` tag is used as a
  rough fallback (e.g. `track` → gravel) — an approximation, not a
  guarantee.
- For inaccurate GPS tracks the match tolerance can be adjusted via
  `MAX_MATCH_DISTANCE_M` in `core/surface_analysis.py`.

## Status

- **Tested:** core logic, all three entry points (core / MCP import /
  skill CLI), `.skill` package build, and the Overpass query end-to-end
  against several real GPX routes (road, bike-park trail, narrow singletrack,
  and a gravel ride exported from Strava activity data via MCP) — including
  retry behaviour on `429`/`504`.
- **Not yet verified:** actual `kubectl apply` against a real k3s cluster
  and whether `readOnlyRootFilesystem: true` runs without issues there (only
  YAML-syntactically checked). The GitHub Actions build itself (arm64+amd64
  via QEMU) has also not yet been verified against a real Actions run.

## License

MIT, see [LICENSE](LICENSE).
