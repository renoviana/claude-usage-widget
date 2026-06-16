"""Lógica do widget independente de toolkit gráfico.

Reúne o que é comum aos frontends (AppIndicator GTK no Linux, bandeja pystray
no Windows/macOS): roda os fetch loops dos providers em threads, mantém o
último resultado de cada um e calcula o que vai pra barra e pro menu.

Nenhum import de GTK/pystray aqui — os frontends consomem `bar_items()` e
`menu_sections()` e traduzem pro widget nativo.
"""

import threading
import time

import widget_settings
from providers import BarItem, Provider, ProviderResult
from providers.notify import notify as _notify


class WidgetCore:
    def __init__(self, providers: list[Provider]):
        if not providers:
            raise ValueError('precisa de pelo menos um provider')
        self.providers = providers
        self.results: dict[str, ProviderResult] = {
            p.name: ProviderResult() for p in providers
        }
        self._on_change = None

    # ---------- ciclo de vida ----------

    def start(self, on_change=None):
        """Dispara um fetch loop por provider em thread daemon.

        `on_change(name, result)` é chamado a cada atualização — SEMPRE a
        partir de uma thread worker, então o frontend é responsável por
        marshalar pro thread de UI (GLib.idle_add no GTK; direto no pystray).
        """
        self._on_change = on_change
        for provider in self.providers:
            threading.Thread(
                target=self._fetch_loop, args=(provider,), daemon=True,
            ).start()

    def _fetch_loop(self, provider: Provider):
        while True:
            self._fetch_once(provider)
            time.sleep(provider.next_refresh_seconds())

    def refresh_now(self):
        """Força um fetch imediato de todos os providers (uma thread cada)."""
        for provider in self.providers:
            threading.Thread(
                target=self._fetch_once, args=(provider,), daemon=True,
            ).start()

    def _fetch_once(self, provider: Provider):
        try:
            result = provider.fetch()
        except Exception as exc:
            result = ProviderResult(error=f'fetch crashed: {exc}')
        self.results[provider.name] = result
        for notif in result.notifications:
            title, body = notif[0], notif[1]
            icon = notif[2] if len(notif) > 2 else None
            sound = notif[3] if len(notif) > 3 else False
            _notify(title, body, icon, sound=sound)
        if self._on_change:
            self._on_change(provider.name, result)

    # ---------- dados pra barra ----------

    def _all_items(self) -> list[tuple[Provider, BarItem]]:
        out = []
        for provider in self.providers:
            for item in provider.items(self.results[provider.name]):
                out.append((provider, item))
        return out

    def split_items(self) -> tuple[list, list]:
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

    def bar_sequence(self) -> list[BarItem]:
        """Todos os BarItems em ordem (fixos primeiro). Usado por frontends
        que rotacionam um item por vez e precisam do ícone de cada um."""
        pinned, rotating = self.split_items()
        return [item for _, item in pinned] + [item for _, item in rotating]

    def all_labels(self) -> list[str]:
        """Todos os labels da barra em ordem (fixos primeiro, depois o resto).

        Usado por frontends que mostram tudo de uma vez (ex.: tooltip da
        bandeja) em vez de rotacionar.
        """
        pinned, rotating = self.split_items()
        return [item.label for _, item in pinned] + [item.label for _, item in rotating]

    # ---------- dados pro menu ----------

    def menu_sections(self) -> list[tuple[str, list]]:
        """[(header, details)] dos providers ativos.

        `details` é uma lista de `str` (linhas informativas) com `None` como
        separador — exatamente o que `Provider.render_menu` devolve. Providers
        idle (header None) ficam de fora.
        """
        sections = []
        for provider in self.providers:
            result = self.results[provider.name]
            header = provider.menu_header(result)
            if not header:
                continue
            details = provider.render_menu(result)
            sections.append((header, details))
        return sections
