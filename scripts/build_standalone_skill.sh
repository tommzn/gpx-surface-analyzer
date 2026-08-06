#!/usr/bin/env bash
# Packages claude-skill/ as a standalone .skill file.
#
# The skill is already self-contained: claude-skill/scripts/core/surface_analysis.py
# is the canonical single source, so no extra copying or import-path patching
# is needed before packaging.
#
# Usage:
#   ./scripts/build_standalone_skill.sh [output-dir]
#
# Prerequisite: skill-creator (from the Anthropic skill catalogue) must be
# available locally. Adjust PACKAGE_SKILL_PY below if needed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${1:-$REPO_ROOT/dist}"
SKILL_DIR="$REPO_ROOT/claude-skill"

# Adjust if package_skill.py lives elsewhere locally.
PACKAGE_SKILL_PY="${PACKAGE_SKILL_PY:-/mnt/skills/examples/skill-creator}"

echo "Packaging $SKILL_DIR ..."
mkdir -p "$OUTPUT_DIR"
(cd "$PACKAGE_SKILL_PY" && python3 -m scripts.package_skill "$SKILL_DIR" "$OUTPUT_DIR")

echo "Done: $OUTPUT_DIR/gpx-surface-analysis.skill"
