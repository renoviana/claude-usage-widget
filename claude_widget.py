import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as AppIndicator

import os
import threading
import time

from providers import (
    Provider, ProviderResult, BarItem,
    ClaudeUsageProvider, FootballProvider, MoonProvider, WeatherProvider,
)
from config_dialog import ConfigDialog
import widget_settings

APP_ID = 'claude-widget'
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'claude-icon.png')
ROTATION_INTERVAL_SECONDS = 10
PIN_SEPARATOR = ' · '


class MultiProviderIndicator:
    def __init__(self, providers: list[Provider]):
        if not providers:
            raise ValueError('precisa de pelo menos um provider')

        self.providers = providers
        self.results: dict[str, ProviderResult] = {
            p.name: ProviderResult() for p in providers
        }
        self._rotation_index = 0
        self._config_window = None

        icon = ICON_PATH if os.path.exists(ICON_PATH) else 'utilities-system-monitor'
        self.indicator = AppIndicator.Indicator.new(
            APP_ID,
            icon,
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_label('carregando…', '')

        self.menu = Gtk.Menu()
        self.indicator.set_menu(self.menu)
        self._rebuild_menu()

        for provider in self.providers:
            threading.Thread(
                target=self._fetch_loop,
                args=(provider,),
                daemon=True,
            ).start()

        GLib.timeout_add_seconds(ROTATION_INTERVAL_SECONDS, self._tick_rotation)

    def _fetch_loop(self, provider: Provider):
        while True:
            try:
                result = provider.fetch()
            except Exception as exc:
                result = ProviderResult(error=f'fetch crashed: {exc}')
            GLib.idle_add(self._on_provider_update, provider.name, result)
            time.sleep(provider.next_refresh_seconds())

    def _on_provider_update(self, name: str, result: ProviderResult):
        self.results[name] = result
        self._rebuild_menu()
        self._render_bar()
        return False

    def _all_items(self) -> list[tuple[Provider, BarItem]]:
        out = []
        for p in self.providers:
            for item in p.items(self.results[p.name]):
                out.append((p, item))
        return out

    def _split_items(self) -> tuple[list, list]:
        """Retorna (pinned, rotating); pinned segue a ordem da config."""
        pinned_ids = list(widget_settings.load().get('pinned') or [])
        pinned_set = set(pinned_ids)
        pinned_by_id: dict[str, tuple] = {}
        rotating: list[tuple] = []
        for prov, item in self._all_items():
            if item.pin_id and item.pin_id in pinned_set:
                pinned_by_id[item.pin_id] = (prov, item)
            else:
                rotating.append((prov, item))
        pinned = [pinned_by_id[pid] for pid in pinned_ids if pid in pinned_by_id]
        return pinned, rotating

    def _render_bar(self):
        pinned, rotating = self._split_items()
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
        _, rotating = self._split_items()
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
        for provider in self.providers:
            result = self.results[provider.name]
            header = provider.menu_header(result)
            if not header:
                continue  # provider idle — não entra no menu
            details = provider.render_menu(result)
            item = Gtk.MenuItem(label=header)
            if details:
                sub = Gtk.Menu()
                for d in details:
                    sub.append(d)
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

    def _on_refresh(self, _item):
        for provider in self.providers:
            threading.Thread(
                target=self._refresh_once,
                args=(provider,),
                daemon=True,
            ).start()

    def _refresh_once(self, provider: Provider):
        try:
            result = provider.fetch()
        except Exception as exc:
            result = ProviderResult(error=f'fetch crashed: {exc}')
        GLib.idle_add(self._on_provider_update, provider.name, result)

    def _on_configure(self, _item):
        if self._config_window and self._config_window.is_visible():
            self._config_window.present()
            return
        self._config_window = ConfigDialog(on_save=self._on_config_saved)
        self._config_window.show_all()

    def _on_config_saved(self):
        # config foi gravada — força refresh imediato em todos os providers
        # pra UI refletir a nova configuração
        self._on_refresh(None)

    def _on_quit(self, _item):
        Gtk.main_quit()


if __name__ == '__main__':
    MultiProviderIndicator([
        ClaudeUsageProvider(),
        FootballProvider(),
        MoonProvider(),
        WeatherProvider(),
    ])
    Gtk.main()
