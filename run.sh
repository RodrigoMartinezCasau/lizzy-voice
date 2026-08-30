#!/usr/bin/env bash
# Solo desarrollo — hereda el micrófono de Cursor. Para 24/7 usa LIZZY.app del Escritorio.
set -euo pipefail
cd "$(dirname "$0")"
echo "⚠ Modo dev: micrófono vía Cursor. Para uso normal: doble clic en ~/Desktop/LIZZY.app"
source .venv/bin/activate 2>/dev/null || {
  echo "Ejecuta primero: python3 -m venv .venv && pip install -r requirements.txt"
  exit 1
}
exec python -m jarvis.main
