# gpx-surface-analyzer

Analysiert GPX-Fahrradrouten und berechnet den prozentualen Anteil
verschiedener Wegoberflächen (Asphalt, Schotter, unbefestigt, Pflaster)
anhand von OpenStreetMap-Daten über die öffentliche Overpass API.

Zwei Nutzungsarten, eine gemeinsame Kernlogik:

- **`mcp-server/`** – MCP-Server für Claude Desktop / Claude Code, stellt
  die Analyse als Tool (`analyze_gpx_surface`, `analyze_gpx_file`) bereit
- **`claude-skill/`** – Claude Skill (SKILL.md + Skript), das Claude
  selbstständig ausführt, wenn ein Nutzer nach der Oberfläche einer
  hochgeladenen GPX-Route fragt

Beide greifen auf `core/surface_analysis.py` zurück – die eigentliche
Logik (GPX-Parsing, Overpass-Abfrage, Matching, Klassifizierung) existiert
nur an einer Stelle.

## Funktionsweise

1. GPX parsen -> Track-Punkte extrahieren
2. Bounding Box der gesamten Route berechnen (+ Puffer)
3. **Eine einzige** Overpass-Abfrage holt alle Wege (`highway=*`) in dieser
   Box inkl. Geometrie und `surface`-Tag – bewusst nicht pro Punkt, um den
   öffentlichen Server zu schonen und die Analyse schnell zu halten
4. Jedes Streckensegment wird per Punkt-zu-Liniensegment-Distanz dem
   nächstgelegenen OSM-Weg zugeordnet (Toleranz: 30m, per Grid-Index
   beschleunigt)
5. Streckenlängen pro Oberflächenkategorie werden aufsummiert und als
   Prozentsatz der Gesamtstrecke zurückgegeben

Kein API-Key nötig – Overpass ist öffentlich zugänglich (siehe
[dev.overpass-api.de](https://dev.overpass-api.de) für Fair-Use-Regeln).
Der öffentliche Server antwortet bei Last gelegentlich mit `429` (Rate
Limit) oder `502`/`503`/`504` (Timeout/Überlastung) – die Abfrage
(`fetch_ways_in_bbox` in `core/surface_analysis.py`) retried solche
transienten Fehler automatisch mit exponentiellem Backoff (bis zu 3
Versuche, Wartezeit verdoppelt sich, respektiert einen `Retry-After`-Header
falls vorhanden). Andere Fehler (z.B. nicht erreichbarer Host) werden
bewusst nicht retried, da ein erneuter Versuch dort nichts ändert.

## Repo-Struktur

```
gpx-surface-analyzer/
├── core/
│   ├── __init__.py
│   └── surface_analysis.py       # gemeinsame Kernlogik (einzige Quelle der Wahrheit)
├── mcp-server/
│   ├── server.py                  # MCP-Wrapper, importiert core/ (stdio + streamable-http)
│   ├── Dockerfile
│   └── requirements.txt
├── claude-skill/
│   ├── SKILL.md
│   ├── requirements.txt
│   └── scripts/
│       └── analyze_surface.py     # CLI-Wrapper, importiert core/
├── k8s/
│   ├── deployment.yaml              # NodePort-Setup fuer privates Heimnetz, nodeSelector arm64
│   ├── service.yaml
│   └── kustomization.yaml
├── scripts/
│   └── build_standalone_skill.sh  # baut ein in sich geschlossenes .skill-Paket
├── .github/
│   └── workflows/
│       └── docker-publish.yml     # baut mcp-server-Image (arm64+amd64), pusht zu ghcr.io auf main/Tags
├── .dockerignore
└── README.md
```

## MCP-Server nutzen

```bash
cd mcp-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

In `claude_desktop_config.json` (oder der MCP-Config von Claude Code):

```json
{
  "mcpServers": {
    "gpx-surface-analyzer": {
      "command": "/absoluter/pfad/zu/gpx-surface-analyzer/mcp-server/venv/bin/python3",
      "args": ["/absoluter/pfad/zu/gpx-surface-analyzer/mcp-server/server.py"]
    }
  }
}
```

### Containerisiert (Docker / Kubernetes)

Für lokale stdio-Nutzung (Claude Desktop/Code) brauchst du **kein**
Docker/K8s – das lohnt sich erst, wenn der Server dauerhaft laufen und per
HTTP erreichbar sein soll. Der Server unterstützt dafür den
`streamable-http`-Transport zusätzlich zu stdio.

Die folgende Anleitung ist auf ein **privates Heimnetz-Cluster auf
Raspberry Pi (k3s), nicht öffentlich erreichbar** zugeschnitten – Zugriff
nur aus dem eigenen LAN über NodePort, kein Ingress/TLS nötig.

**1. Image bauen und zu ghcr.io pushen**

Passiert automatisch über `.github/workflows/docker-publish.yml`: bei jedem
Push auf `main` (der `core/` oder `mcp-server/` ändert) sowie bei
Versions-Tags (`v*`) baut GitHub Actions das Image für `linux/arm64` *und*
`linux/amd64` und pusht es nach
`ghcr.io/<github-user>/gpx-surface-mcp:latest` (zusätzlich getaggt mit
Short-SHA bzw. Versionsnummer bei Tags). Auf Pull Requests wird nur
gebaut, nicht gepusht (Validierung ohne Veröffentlichung). Kein manueller
Schritt nötig – einfach `git push` und in der Actions-Tab den Lauf
beobachten. Das erstmalig erzeugte GHCR-Package ist standardmäßig
**privat**; das GitHub-Actions-Token (`GITHUB_TOKEN`) hat automatisch
Push-Rechte darauf, für den Pull auf den Pi-Nodes siehe Pull-Secret unten.

Manuell/lokal bauen und pushen geht weiterhin, z.B. für schnelle
Iterationen ohne CI-Wartezeit. Raspberry Pi läuft auf ARM64 (bei 64-Bit-OS
– mit `uname -m` auf dem Pi prüfen, sollte `aarch64` zeigen). Falls du von
einem Apple-Silicon-Mac aus baust (z.B. deinem Mac Mini M1), geht das
nativ ohne Emulation:

```bash
docker buildx build \
  --platform linux/arm64 \
  -f mcp-server/Dockerfile \
  -t ghcr.io/<dein-github-user>/gpx-surface-mcp:latest \
  --push .
```

Von einem x86-Rechner aus braucht `buildx` dafür QEMU-Emulation (deutlich
langsamer, aber funktioniert genauso mit demselben Befehl).

Falls das ghcr.io-Package **privat** bleibt, brauchen die Pis ein
Pull-Secret (einmalig anlegen):
```bash
kubectl create secret docker-registry ghcr-pull-secret \
  --docker-server=ghcr.io \
  --docker-username=<dein-github-user> \
  --docker-password=<github-PAT-mit-read:packages-scope> \
  --docker-email=<deine-email>
```
und in `k8s/deployment.yaml` den auskommentierten `imagePullSecrets`-Block
aktivieren. Einfacher: Package in den GitHub-Package-Settings auf "Public"
stellen, dann entfällt das Secret komplett.

**2. In k3s deployen**

`k8s/deployment.yaml`: `image:` auf dein gepushtes Image anpassen, dann:
```bash
kubectl apply -k k8s/
kubectl get pods -w
```

**3. Erreichbarkeit testen**

Der Service ist als `NodePort` auf Port `30800` exponiert – erreichbar
über die IP **jedes beliebigen** Node im Cluster (auch wenn der Pod nur
auf einem läuft, k3s routet automatisch weiter):
```bash
curl -i http://<ip-eines-beliebigen-pi>:30800/mcp
```
Für die Claude-Code-Config auf deinem Mac Mini dann `http://<pi-ip>:30800/mcp`
als Remote-MCP-Endpunkt eintragen.

**Lokal mit Docker testen (bevor es auf den Pis läuft):**
```bash
docker build -f mcp-server/Dockerfile -t gpx-surface-mcp:latest .
docker run --rm -p 8000:8000 gpx-surface-mcp:latest
# MCP-Endpunkt: http://localhost:8000/mcp
```

> **Egress-Hinweis:** Der Server braucht ausgehenden HTTPS-Zugriff auf
> `overpass-api.de`. k3s hat standardmäßig keine restriktiven
> Egress-`NetworkPolicy`s – im Heimnetz-Setup ist das also normalerweise
> kein Thema, solange dein Router/deine Firewall ausgehendes HTTPS erlaubt.

## Claude Skill nutzen

Direkt aus dem Repo heraus verweisen (Skript importiert `core/` relativ):

```bash
pip install -r claude-skill/requirements.txt --break-system-packages
python3 claude-skill/scripts/analyze_surface.py /pfad/zur/route.gpx
```

Für die Installation als eigenständiges `.skill`-Paket (unabhängig vom
Repo, z.B. über die "Save skill"-Karte in Claude.ai) muss `core/` mit
hineingebündelt werden:

```bash
./scripts/build_standalone_skill.sh ./dist
```

Erzeugt `dist/gpx-surface-analysis.skill`.

> **Netzwerk-Hinweis:** Der Skill braucht Zugriff auf `overpass-api.de`.
> In der sandboxed Code-Execution-Umgebung von claude.ai ist dieser Host
> nicht freigeschaltet – der Skill funktioniert zuverlässig in Claude Code
> (lokal) oder anderen Umgebungen mit freiem Internetzugriff.

## Beispiel-Ausgabe

```json
{
  "total_distance_km": 42.7,
  "matched_distance_km": 41.9,
  "surface_percentages": {
    "asphalt": 68.4,
    "schotter": 24.1,
    "unbefestigt": 5.2,
    "pflaster": 2.3
  },
  "unmatched_percent": 1.9
}
```

## Grenzen

- Sehr lange Routen (>150 km) bzw. Routen mit großer Bounding Box (>~15km
  Kantenlänge) führen zu größeren Overpass-Antworten und können trotz
  automatischem Retry gelegentlich mit Timeout fehlschlagen, wenn der
  öffentliche Server stark ausgelastet ist – ein erneuter manueller Versuch
  hilft in dem Fall meist.
- Fehlt in OSM das `surface`-Tag, wird grob über den `highway`-Tag
  geschätzt (z.B. `track` → Schotter) – eine Näherung, keine Garantie.
- Bei ungenauem GPS-Track lässt sich die Match-Toleranz über
  `MAX_MATCH_DISTANCE_M` in `core/surface_analysis.py` anpassen.

## Status

- **Getestet:** Kernlogik, alle drei Einstiegspunkte (core/MCP-Import/
  Skill-CLI), `.skill`-Paket-Build, und die eigentliche Overpass-Abfrage
  end-to-end gegen mehrere reale GPX-Routen (Straße, Bikepark-Trail,
  Schmaler-Trail, sowie ein aus Strava-Aktivitätsdaten via MCP exportierter
  Gravel-Ride) – inklusive Retry-Verhalten bei `429`/`504`.
- **Noch nicht verifiziert:** tatsächliches `kubectl apply` gegen ein
  echtes k3s-Cluster und ob `readOnlyRootFilesystem: true` dort
  problemlos läuft (nur YAML-syntaktisch geprüft). Der GitHub-Actions-Build
  selbst (arm64+amd64 via QEMU) ist ebenfalls noch nicht gegen einen echten
  Actions-Lauf verifiziert worden.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
