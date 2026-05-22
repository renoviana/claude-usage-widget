#!/usr/bin/env bash
# Instala o claude-widget como AppIndicator na barra do topo do GNOME/Ubuntu.
# Roda sem sudo (usa pip --user e instala apt deps com prompt se faltar).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTOSTART_DIR="$HOME/.config/autostart"
DESKTOP_FILE="$AUTOSTART_DIR/claude-widget.desktop"
PYTHON="${PYTHON:-/usr/bin/python3}"

log() { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }

# 1. Verifica Python do sistema (precisa do GTK/AyatanaAppIndicator do APT)
if [ ! -x "$PYTHON" ]; then
    err "Python não encontrado em $PYTHON. Defina PYTHON=/path/to/python3 e rode de novo."
    exit 1
fi

# 2. Verifica deps do sistema (GTK + AppIndicator)
log "Verificando dependências do sistema..."
missing_apt=()
"$PYTHON" -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" 2>/dev/null || missing_apt+=("python3-gi" "gir1.2-gtk-3.0")
"$PYTHON" -c "import gi; gi.require_version('AyatanaAppIndicator3', '0.1'); from gi.repository import AyatanaAppIndicator3" 2>/dev/null || missing_apt+=("gir1.2-ayatanaappindicator3-0.1")

if [ ${#missing_apt[@]} -gt 0 ]; then
    log "Instalando pacotes apt: ${missing_apt[*]}"
    sudo apt update
    sudo apt install -y "${missing_apt[@]}"
fi

# 3. Instala libs Python
log "Instalando dependências Python (curl_cffi, Pillow)..."
"$PYTHON" -m pip install --user --upgrade -r "$REPO_DIR/requirements.txt"

# 4. Garante o ícone (converte .ico → .png se necessário)
if [ ! -f "$REPO_DIR/claude-icon.png" ] && [ -f "$REPO_DIR/claude-icon.ico" ]; then
    log "Convertendo claude-icon.ico → .png..."
    "$PYTHON" - <<PY
from PIL import Image
img = Image.open("$REPO_DIR/claude-icon.ico")
if hasattr(img, 'n_frames'):
    sizes = []
    for i in range(img.n_frames):
        img.seek(i)
        sizes.append((img.size[0], i))
    img.seek(max(sizes)[1])
img.save("$REPO_DIR/claude-icon.png", "PNG")
PY
fi

# 5. Cria autostart
log "Criando autostart em $DESKTOP_FILE..."
mkdir -p "$AUTOSTART_DIR"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Claude Widget
Comment=Exibe o consumo do Claude na barra do topo
Exec=$PYTHON $REPO_DIR/claude_widget.py
Icon=$REPO_DIR/claude-icon.png
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
StartupNotify=false
Categories=Utility;
EOF

# 6. Aviso sobre cookies
log ""
log "✔ Instalação concluída."
log ""
log "Pré-requisito: você precisa estar logado em https://claude.ai no Firefox."
log "Se usa Chrome/outro navegador, crie ~/.config/claude-widget/cookies.json (veja README)."
log ""
log "Para iniciar agora sem reiniciar a sessão:"
log "  $PYTHON $REPO_DIR/claude_widget.py &"
