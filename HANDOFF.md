# Handoff: gpx-surface-analyzer

Kontext-Dokument für die Weiterarbeit. Fasst zusammen, welche
Entscheidungen getroffen wurden und was (noch) offen/ungetestet ist.
Für Nutzung/Setup siehe [README.md](README.md).

## Ausgangsfrage

GPX-Fahrradrouten analysieren: welcher Anteil verläuft auf Asphalt,
Schotter, unbefestigten Wegen etc.? Datenquelle: OpenStreetMap über die
öffentliche Overpass API (`overpass-api.de`, kein API-Key nötig).

## Architektur-Entscheidungen

- **Eine gemeinsame Kernlogik** (`core/surface_analysis.py`), genutzt von
  MCP-Server (`mcp-server/`) und Claude Skill (`claude-skill/`), damit die
  Matching-Logik nur an einer Stelle gepflegt werden muss.
- **Eine einzige Overpass-Abfrage pro Route** (Bounding Box der gesamten
  Route + 300m Puffer), nicht eine Abfrage pro GPX-Punkt – schont den
  öffentlichen Server, ist massiv schneller.
- **MCP-SDK-API**: Nutzt `mcp.server.mcpserver.MCPServer` (Benennung des
  offiziellen Python-SDK zum Zeitpunkt der Entwicklung, `mcp==2.0.0`).
  Falls ein älteres SDK vorliegt (noch `FastMCP`): Import/Klasse
  entsprechend zurückbenennen, Rest der Tool-Logik bleibt gleich.
- **Transport**: `server.py` wählt per `MCP_TRANSPORT`-Env-Var zwischen
  `stdio` (Default, lokal) und `streamable-http` (Docker/K8s).
- **Deployment-Ziel**: Privates k3s-Cluster auf Raspberry Pi im Heimnetz,
  nicht öffentlich erreichbar. Deshalb NodePort statt Ingress/TLS,
  `nodeSelector: kubernetes.io/arch: arm64`, `readOnlyRootFilesystem: true`
  mit `emptyDir` auf `/tmp` als Sicherheitsnetz.
- **Image-Distribution**: ghcr.io statt lokalem Import, jetzt automatisiert
  über `.github/workflows/docker-publish.yml` (baut arm64+amd64 via
  buildx/QEMU, pusht auf Push zu `main` bzw. bei `v*`-Tags; PRs bauen nur
  zur Validierung, ohne Push).

## Status: Getestet

- Kernlogik (GPX-Parsing, Haversine, Punkt-zu-Segment-Distanz,
  Grid-Index-Matching, Surface-Klassifizierung).
- Alle drei Einstiegspunkte (core-Modul direkt, MCP-Server-Import,
  Skill-CLI von fremdem Arbeitsverzeichnis aus).
- YAML-Syntax und Feld-Konsistenz von `k8s/*.yaml` (Selector, Labels,
  Ports, Volumes zwischen Deployment/Service).
- `.skill`-Paket-Build via `scripts/build_standalone_skill.sh`.
- **Overpass-API end-to-end**, gegen mehrere reale GPX-Routen:
  - Straßenroute (Odelshausen–Dachau, 24km, 83% Asphalt)
  - Bikepark-Trail (Hohenwart, 33km, 59% Schotter)
  - Schmaler Wurzeltrail (Tegernbach, 19km, 49% Schotter/37% unbefestigt)
  - Längere Straßen-Tour (69km, 5506 Punkte, 63% Asphalt)
  - Gravel-Ride aus Strava-Aktivitätsdaten exportiert (via Strava-MCP,
    `get_activity_streams` → GPX gebaut, 68km, 11479 Punkte, 86% Asphalt)
  - Alle mit `unmatched_percent: 0.0` – 30m-Toleranz funktioniert gut
    gegen reale OSM-Daten in den getesteten Regionen (Bayern).
- **Retry-Verhalten bei transienten Overpass-Fehlern**: Der öffentliche
  Server antwortet unter Last mit `429` (Rate Limit) oder gelegentlich
  `502`/`503`/`504`. `fetch_ways_in_bbox` retried das jetzt automatisch
  (bis zu 3 Versuche, exponentielles Backoff ab 5s, respektiert
  `Retry-After`-Header). Verifiziert sowohl gegen echte 429-Antworten
  (mehrere Routen kurz hintereinander analysiert) als auch per gemocktem
  Unit-Test (429×2→Erfolg, 404 sofortiger Fail ohne Retry, dauerhaftes 429
  → Fail nach Ausschöpfen aller Versuche). Bei sehr großer Bounding Box
  (~15×20km) reichten die 3 Retries in einem Fall trotzdem nicht aus –
  ein weiterer manueller Versuch war nötig. Andere Fehler (z.B.
  `ConnectionError`, weil der Host nicht erreichbar ist – etwa in der
  sandboxed claude.ai-Umgebung) werden bewusst NICHT retried.

## Status: NICHT getestet

- **Der GitHub-Actions-Workflow selbst** (`docker-publish.yml`) wurde
  noch nie gegen einen echten Actions-Lauf verifiziert – nur lokal auf
  YAML-Syntax/Plausibilität geprüft. Insbesondere ungetestet: ob der
  `linux/arm64`-Build via QEMU auf `ubuntu-latest` in akzeptabler Zeit
  durchläuft, und ob `GITHUB_TOKEN` mit `packages: write` tatsächlich
  ausreicht, um ins Repo-eigene GHCR-Package zu pushen (sollte laut
  GitHub-Doku funktionieren, aber nie live gesehen).
- **Docker-Build lokal** (`docker build`/`buildx`) – weiterhin nie
  tatsächlich ausgeführt, da in keiner bisherigen Session Docker verfügbar
  war.
- **k3s-Deployment** – kein echtes Cluster verfügbar, Manifeste nur
  YAML-syntaktisch und auf Feld-Konsistenz geprüft, nie mit `kubectl
  apply` gegen ein echtes Cluster.
- **`readOnlyRootFilesystem: true`** – ob das in der Praxis auf
  k3s/containerd ohne Probleme läuft, ist unverifiziert.
- **`.skill`-Paket in claude.ai installieren** und Trigger-Erkennung der
  SKILL.md-Beschreibung in echten Konversationen prüfen – nur strukturell
  validiert, nie ein echter Trigger-Test.

→ **Empfehlung für die nächsten Schritte:** Ersten echten Push auf `main`
beobachten (Actions-Tab), um den Workflow zu verifizieren. Danach Image
tatsächlich auf einem Pi/k3s deployen und die vier k3s-bezogenen Punkte
oben verifizieren, bevor mehr Features draufgesattelt werden.

## Repo-Struktur

```
gpx-surface-analyzer/
├── core/
│   ├── __init__.py
│   └── surface_analysis.py       # einzige Quelle der Analyse-Logik (inkl. Retry/Backoff)
├── mcp-server/
│   ├── server.py                  # MCP-Wrapper (stdio + streamable-http)
│   ├── Dockerfile
│   └── requirements.txt
├── claude-skill/
│   ├── SKILL.md
│   ├── requirements.txt
│   └── scripts/analyze_surface.py # CLI-Wrapper
├── k8s/
│   ├── deployment.yaml            # NodePort-Setup, arm64 nodeSelector
│   ├── service.yaml
│   └── kustomization.yaml
├── scripts/
│   └── build_standalone_skill.sh  # baut in sich geschlossenes .skill-Paket
├── .github/workflows/
│   └── docker-publish.yml         # baut+pusht Image nach ghcr.io (main/Tags)
├── .dockerignore
├── .gitignore
├── README.md
└── LICENSE (MIT)
```
