#!/usr/bin/env bash
set -euo pipefail

log() { printf '\033[1;34m[uninstall]\033[0m %s\n' "$*"; }

log "Parando processo claude_widget.py..."
pkill -f claude_widget.py 2>/dev/null || true

log "Removendo autostart..."
rm -f "$HOME/.config/autostart/claude-widget.desktop"

log "✔ Removido. Os arquivos do repo permanecem; apague a pasta manualmente se quiser."
log "  Para remover as libs Python: pip uninstall --user curl_cffi"
