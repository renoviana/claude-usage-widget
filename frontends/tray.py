"""Frontend Windows/macOS: ícone na bandeja (system tray) via pystray.

Ao contrário do AppIndicator do GNOME, a bandeja não exibe texto ao lado do
ícone. Então o consumo aparece de duas formas:

- **tooltip** (hover): todos os items da barra, um por linha;
- **menu** (clique direito): cada provider com seu submenu de detalhes.

O ícone em si fica estático (logo do Claude).
"""

import os
import subprocess
import sys

import pystray
from PIL import Image

import widget_settings
from providers import MENU_SEPARATOR
from widget_core import WidgetCore

APP_ID = 'claude-widget'
ICON_PNG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'claude-icon.png'
)
ICON_ICO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'claude-icon.ico'
)
# szTip do Windows aceita 127 chars + terminador; trunca pra caber.
TOOLTIP_MAX = 127


def _load_image() -> Image.Image:
    for path in (ICON_PNG, ICON_ICO):
        if os.path.exists(path):
            return Image.open(path)
    # fallback: quadrado laranja simples, pra nunca ficar sem ícone
    return Image.new('RGB', (64, 64), (204, 120, 92))


def _open_config_file():
    """Abre o config.json no editor padrão do SO (config GUI é só no Linux)."""
    path = widget_settings.CONFIG_PATH
    if not os.path.exists(path):
        # materializa os defaults pra ter o que editar
        widget_settings.save(widget_settings.load())
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception:
        pass


class TrayIndicator:
    def __init__(self, core: WidgetCore):
        self.core = core
        self.icon = pystray.Icon(
            APP_ID,
            icon=_load_image(),
            title='Claude Widget',
            menu=self._build_menu(),
        )

    # ---------- montagem ----------

    def _tooltip(self) -> str:
        labels = self.core.all_labels()
        text = '\n'.join(labels) if labels else 'Claude Widget'
        return text[:TOOLTIP_MAX]

    def _build_menu(self) -> pystray.Menu:
        items = []
        for header, details in self.core.menu_sections():
            sub = [self._detail_item(d) for d in details]
            if sub:
                items.append(pystray.MenuItem(header, pystray.Menu(*sub)))
            else:
                items.append(pystray.MenuItem(header, None, enabled=False))

        if items:
            items.append(pystray.Menu.SEPARATOR)

        items.append(pystray.MenuItem('Atualizar agora', self._on_refresh))
        items.append(pystray.MenuItem('Configurar (abrir JSON)…', self._on_configure))
        items.append(pystray.MenuItem('Sair', self._on_quit))
        return pystray.Menu(*items)

    @staticmethod
    def _detail_item(line):
        if line is MENU_SEPARATOR:
            return pystray.Menu.SEPARATOR
        return pystray.MenuItem(line, None, enabled=False)

    # ---------- atualização ----------

    def _on_change(self, _name, _result):
        # pystray permite mexer no ícone de qualquer thread; protege mesmo assim
        try:
            self.icon.title = self._tooltip()
            self.icon.menu = self._build_menu()
            self.icon.update_menu()
        except Exception:
            pass

    # ---------- ações do menu ----------

    def _on_refresh(self, _icon, _item):
        self.core.refresh_now()

    def _on_configure(self, _icon, _item):
        _open_config_file()

    def _on_quit(self, icon, _item):
        icon.stop()

    # ---------- loop ----------

    def run(self):
        self.core.start(on_change=self._on_change)

        def _setup(icon):
            icon.visible = True
            self._on_change(None, None)  # primeira renderização

        # bloqueia na thread principal (obrigatório no Windows)
        self.icon.run(setup=_setup)


def run(providers):
    TrayIndicator(WidgetCore(providers)).run()
