#!/usr/bin/env bash
# Baut aus claude-skill/ + core/ ein in sich geschlossenes Skill-Verzeichnis,
# das unabhaengig vom restlichen Repo als .skill installiert werden kann.
#
# Grund: das Repo haelt core/surface_analysis.py nur EINMAL (DRY), ein
# .skill-Paket muss aber in sich geschlossen sein - also wird core/ hier
# in eine temporaere Kopie des Skill-Ordners hineinkopiert, bevor gepackt
# wird.
#
# Nutzung:
#   ./scripts/build_standalone_skill.sh [output-dir]
#
# Voraussetzung: skill-creator SKILL.md (aus Anthropics Skill-Katalog) mit
# scripts/package_skill.py muss lokal verfuegbar sein. Pfad ggf. unten
# anpassen (PACKAGE_SKILL_PY).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${1:-$REPO_ROOT/dist}"
BUILD_DIR="$(mktemp -d)"
STANDALONE_SKILL_DIR="$BUILD_DIR/gpx-surface-analysis"

# Anpassen, falls package_skill.py woanders liegt (z.B. lokaler
# Anthropic-Skill-Katalog unter /mnt/skills/examples/skill-creator).
PACKAGE_SKILL_PY="${PACKAGE_SKILL_PY:-/mnt/skills/examples/skill-creator}"

echo "Baue eigenstaendiges Skill-Verzeichnis in $STANDALONE_SKILL_DIR ..."
mkdir -p "$STANDALONE_SKILL_DIR/scripts"
mkdir -p "$STANDALONE_SKILL_DIR/scripts/core"

cp "$REPO_ROOT/claude-skill/SKILL.md" "$STANDALONE_SKILL_DIR/SKILL.md"
cp "$REPO_ROOT/claude-skill/requirements.txt" "$STANDALONE_SKILL_DIR/requirements.txt"
cp "$REPO_ROOT/claude-skill/scripts/analyze_surface.py" "$STANDALONE_SKILL_DIR/scripts/analyze_surface.py"
cp "$REPO_ROOT/core/surface_analysis.py" "$STANDALONE_SKILL_DIR/scripts/core/surface_analysis.py"
cp "$REPO_ROOT/core/__init__.py" "$STANDALONE_SKILL_DIR/scripts/core/__init__.py"

# Im eigenstaendigen Paket liegt core/ direkt neben dem Skript, nicht zwei
# Ebenen darueber - Importpfad im kopierten Skript entsprechend anpassen.
python3 - "$STANDALONE_SKILL_DIR/scripts/analyze_surface.py" <<'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    content = f.read()
content = content.replace(
    "REPO_ROOT = Path(__file__).resolve().parent.parent.parent",
    "REPO_ROOT = Path(__file__).resolve().parent",
)
with open(path, "w") as f:
    f.write(content)
PYEOF

echo "Packe .skill-Datei ..."
mkdir -p "$OUTPUT_DIR"
(cd "$PACKAGE_SKILL_PY" && python3 -m scripts.package_skill "$STANDALONE_SKILL_DIR" "$OUTPUT_DIR")

rm -rf "$BUILD_DIR"
echo "Fertig: $OUTPUT_DIR/gpx-surface-analysis.skill"
