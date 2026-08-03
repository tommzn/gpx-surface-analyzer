---
name: gpx-surface-analysis
description: Analysiert eine GPX-Fahrradroute und berechnet den prozentualen Anteil verschiedener Wegoberflächen (Asphalt, Schotter, unbefestigt, Pflaster) anhand von OpenStreetMap-Daten. Immer verwenden, wenn der Nutzer nach dem Oberflächen-Anteil, Schotter/Asphalt-Verhältnis, "wie viel Prozent Gravel/unbefestigt" oder der Wegbeschaffenheit einer hochgeladenen oder referenzierten .gpx-Datei fragt - auch wenn er nur "analysiere meine Strecke" oder "wie sieht der Untergrund aus" sagt, ohne "Oberfläche" explizit zu erwähnen.
---

# GPX Surface Analysis

Berechnet, welcher Anteil einer gefahrenen (oder geplanten) Fahrradroute auf
Asphalt, Schotter, unbefestigten Wegen etc. verläuft. Datenquelle ist
OpenStreetMap über die öffentliche Overpass API (kein API-Key nötig).

Die eigentliche Analyse-Logik liegt in `../core/surface_analysis.py` (Teil
des `gpx-surface-analyzer`-Repos) und wird auch vom MCP-Server im selben
Repo genutzt. Dieses Skill-Skript ist nur ein CLI-Wrapper darum.

## Wann dieser Skill greift

- Nutzer lädt eine `.gpx`-Datei hoch und fragt nach Oberfläche/Untergrund/Belag
- Nutzer fragt "wie viel % meiner Strava-Tour war Schotter/Gravel/Asphalt"
- Nutzer möchte mehrere Routen hinsichtlich Wegbeschaffenheit vergleichen

## Voraussetzung: Internetzugriff

Das Skript braucht ausgehenden HTTPS-Zugriff auf `overpass-api.de`. In der
sandboxed Ausführungsumgebung von Claude.ai (claude.ai Chat mit
Code-Execution) ist dieser Host **nicht** in der Netzwerk-Whitelist – das
Skript schlägt dort mit einem Verbindungsfehler fehl. Es funktioniert
zuverlässig in Umgebungen mit freiem Internetzugriff, z.B.:

- **Claude Code** (lokal auf dem eigenen Rechner)
- **Claude Cowork** (falls dort Netzwerkzugriff erlaubt ist)

Wenn eine Ausführung mit "Connection refused" oder ähnlichem fehlschlägt,
sag dem Nutzer direkt, dass es an den Netzwerk-Einschränkungen der
aktuellen Umgebung liegt, statt es mehrfach erneut zu versuchen.

## Voraussetzung: Repo-Struktur

Dieses Skript importiert `core.surface_analysis` relativ zum Repo-Root
(zwei Ebenen über `scripts/`). Es muss also innerhalb des geklonten
`gpx-surface-analyzer`-Repos liegen, nicht isoliert kopiert werden.

## Vorgehen

1. **Abhängigkeiten sicherstellen** (einmalig, falls nicht vorhanden):
   ```bash
   pip install -r <repo-root>/claude-skill/requirements.txt --break-system-packages
   ```

2. **Skript ausführen** mit dem Pfad zur GPX-Datei:
   ```bash
   python3 <repo-root>/claude-skill/scripts/analyze_surface.py /pfad/zur/route.gpx
   ```
   Optional Ergebnis direkt in eine Datei schreiben:
   ```bash
   python3 <repo-root>/claude-skill/scripts/analyze_surface.py /pfad/zur/route.gpx --output ergebnis.json
   ```

3. **Ergebnis interpretieren und dem Nutzer zusammenfassen.** Das Skript
   gibt JSON zurück, z.B.:
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
   Nicht nur das rohe JSON ausgeben, sondern die Zahlen in normaler Sprache
   einordnen (z.B. "Deine Route war zu gut zwei Dritteln Asphalt, knapp ein
   Viertel Schotter").

## Funktionsweise (Hintergrund, bei Rückfragen)

- Eine einzelne Overpass-Abfrage holt alle `highway=*`-Wege in der
  Bounding Box der gesamten Route (statt einer Abfrage pro GPX-Punkt –
  schont den öffentlichen Server und ist deutlich schneller).
- Jedes Streckensegment wird per Punkt-zu-Liniensegment-Distanz dem
  nächstgelegenen OSM-Weg zugeordnet (Toleranz: 30m).
- Fehlt das `surface`-Tag in OSM, wird grob über den `highway`-Tag
  geschätzt (z.B. `track` → Schotter, `cycleway` → Asphalt). Das ist eine
  Näherung, keine Garantie – bei Rückfragen des Nutzers zur Genauigkeit
  transparent machen.
- `unmatched_percent` zeigt den Anteil, der keinem OSM-Weg zugeordnet
  werden konnte (z.B. abseits kartierter Wege oder bei lückenhaften
  OSM-Daten).

## Grenzen

- Sehr lange Routen (>150 km) führen zu größeren Overpass-Antworten und
  etwas längerer Laufzeit, bleiben aber grundsätzlich handhabbar.
- Bei ungenauem GPS-Track (z.B. dichter Wald) kann die 30m-Toleranz in
  `core/surface_analysis.py` (Konstante `MAX_MATCH_DISTANCE_M`) bei Bedarf
  erhöht werden.

## Als eigenständiges .skill-Paket verteilen

Für die Installation über die Claude-Skill-Karte (unabhängig vom Repo)
muss `core/surface_analysis.py` mit in den Skill-Ordner kopiert werden,
da ein `.skill`-Paket in sich geschlossen sein muss. Siehe
`scripts/build_standalone_skill.sh` im Repo-Root dafür.
