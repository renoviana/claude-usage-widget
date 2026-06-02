from datetime import datetime, timedelta, timezone

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import widget_settings

from . import _format
from .base import BarItem, Provider, ProviderResult

# Referência de lua cheia conhecida (UTC) e período sinódico médio em dias.
# Precisão da estimativa: ±algumas horas (suficiente pra exibir a data certa).
_REF_FULL_MOON_UTC = datetime(2000, 1, 21, 4, 40, tzinfo=timezone.utc)
_SYNODIC_PERIOD_DAYS = 29.53058868

_WITHIN_DAYS = 7  # só mostra se a próxima lua cheia for dentro dessa janela


def _next_full_moon_utc(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    delta = (now - _REF_FULL_MOON_UTC).total_seconds() / 86400
    n = int(delta // _SYNODIC_PERIOD_DAYS) + 1
    while True:
        candidate = _REF_FULL_MOON_UTC + timedelta(days=n * _SYNODIC_PERIOD_DAYS)
        if candidate > now:
            return candidate
        n += 1


class MoonProvider(Provider):
    name = 'moon'
    refresh_interval = 3600  # 1h é mais que suficiente

    @staticmethod
    def _is_enabled() -> bool:
        return bool((widget_settings.load().get('moon') or {}).get('enabled'))

    def fetch(self) -> ProviderResult:
        if not self._is_enabled():
            return ProviderResult()
        full_moon_utc = _next_full_moon_utc()
        return ProviderResult(data={'next_full_moon_utc': full_moon_utc})

    def _local_full_moon(self, result: ProviderResult) -> datetime | None:
        if not result.data:
            return None
        full = result.data.get('next_full_moon_utc')
        if not full:
            return None
        return full.astimezone()

    def items(self, result: ProviderResult) -> list[BarItem]:
        if not self._is_enabled():
            return []
        local = self._local_full_moon(result)
        if not local:
            return []
        today = datetime.now().astimezone().date()
        if (local.date() - today).days >= _WITHIN_DAYS:
            return []
        when = _format.format_when(local, include_time=False)
        return [BarItem(
            label=f'🌕 {when}',
            icon_path='weather-clear-night',
            pin_id=self.name,
        )]

    def menu_header(self, result: ProviderResult) -> str | None:
        if not self._is_enabled():
            return None
        local = self._local_full_moon(result)
        if not local:
            return None
        when = _format.format_when(local, include_time=False)
        return f'🌕 {when}'

    def render_menu(self, result: ProviderResult) -> list:
        local = self._local_full_moon(result)
        if not local:
            return []
        item = Gtk.MenuItem(label=local.strftime('%d/%m %H:%M (local)'))
        item.set_sensitive(False)
        return [item]
