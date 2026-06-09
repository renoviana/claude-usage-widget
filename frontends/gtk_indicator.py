"""Frontend Linux: AppIndicator na barra do topo do GNOME via GTK3.

Mostra um label de texto ao lado do ícone, rotacionando os items não-fixados
a cada poucos segundos e mantendo os fixados sempre visíveis.
"""

import os

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as AppIndicator

from providers import MENU_SEPARATOR
from widget_core import WidgetCore
from config_dialog import ConfigDialog

APP_ID = 'claude-widget'
ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'claude-icon.png'
)
ROTATION_INTERVAL_SECONDS = 10
PIN_SEPARATOR = ' · '


class GtkIndicator:
    def __init__(self, core: WidgetCore):
        self.core = core
        self._rotation_index = 0
        self._config_window = None

        icon = ICON_PATH if os.path.exists(ICON_PATH) else 'utilities-system-monitor'
        self.indicator = AppIndicator.Indicator.new(
            APP_ID, icon, AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_label('carregando…', '')

        self.menu = Gtk.Menu()
        self.indicator.set_menu(self.menu)
        self._rebuild_menu()

        self.core.start(on_change=self._on_change)
        GLib.timeout_add_seconds(ROTATION_INTERVAL_SECONDS, self._tick_rotation)

    def _on_change(self, _name, _result):
        # chamado de uma thread worker — marshala pro thread de UI
        GLib.idle_add(self._on_ui_update)

    def _on_ui_update(self):
        self._rebuild_menu()
        self._render_bar()
        return False

    def _render_bar(self):
        pinned, rotating = self.core.split_items()
        if not pinned and not rotating:
            self.indicator.set_label('—', '')
            return

        pinned_text = PIN_SEPARATOR.join(item.label for _, item in pinned)

        rotating_text = ''
        rotating_icon_pair = None
        if rotating:
            if self._rotation_index >= len(rotating):
                self._rotation_index = 0
            prov_r, item_r = rotating[self._rotation_index]
            rotating_text = item_r.label
            if item_r.icon_path:
                rotating_icon_pair = (item_r.icon_path, prov_r.name)

        # Rotativo logo após o ícone (esquerda), fixos na direita.
        if pinned_text and rotating_text:
            label = f'{rotating_text}{PIN_SEPARATOR}{pinned_text}'
        elif pinned_text:
            label = pinned_text
        else:
            label = rotating_text or '—'
        self.indicator.set_label(label, '')

        # Ícone vem APENAS do rotativo atual — items fixos contribuem só com
        # texto, pra evitar conflito visual entre o ícone e o que está rolando.
        if rotating_icon_pair:
            icon_path, prov_name = rotating_icon_pair
            self.indicator.set_icon_full(icon_path, prov_name)

    def _tick_rotation(self):
        _, rotating = self.core.split_items()
        if len(rotating) > 1:
            self._rotation_index = (self._rotation_index + 1) % len(rotating)
        else:
            self._rotation_index = 0
        # sempre re-renderiza pra refletir mudanças derivadas do tempo
        # (ex.: minuto do jogo avançando entre fetches)
        self._render_bar()
        return True

    def _rebuild_menu(self):
        for child in self.menu.get_children():
            self.menu.remove(child)

        appended_any = False
        for header, details in self.core.menu_sections():
            item = Gtk.MenuItem(label=header)
            rendered = [self._detail_widget(d) for d in details]
            if rendered:
                sub = Gtk.Menu()
                for widget in rendered:
                    sub.append(widget)
                item.set_submenu(sub)
            else:
                item.set_sensitive(False)
            self.menu.append(item)
            appended_any = True

        if appended_any:
            self.menu.append(Gtk.SeparatorMenuItem())

        configure = Gtk.MenuItem(label='Configurar…')
        configure.connect('activate', self._on_configure)
        self.menu.append(configure)

        refresh = Gtk.MenuItem(label='Atualizar agora')
        refresh.connect('activate', self._on_refresh)
        self.menu.append(refresh)

        quit_item = Gtk.MenuItem(label='Sair')
        quit_item.connect('activate', self._on_quit)
        self.menu.append(quit_item)

        self.menu.show_all()

    @staticmethod
    def _detail_widget(line):
        if line is MENU_SEPARATOR:
            return Gtk.SeparatorMenuItem()
        item = Gtk.MenuItem(label=line)
        item.set_sensitive(False)
        return item

    def _on_refresh(self, _item):
        self.core.refresh_now()

    def _on_configure(self, _item):
        if self._config_window and self._config_window.is_visible():
            self._config_window.present()
            return
        self._config_window = ConfigDialog(on_save=self._on_config_saved)
        self._config_window.show_all()

    def _on_config_saved(self):
        # config foi gravada — força refresh imediato pra UI refletir a mudança
        self.core.refresh_now()

    def _on_quit(self, _item):
        Gtk.main_quit()


def run(providers):
    GtkIndicator(WidgetCore(providers))
    Gtk.main()
