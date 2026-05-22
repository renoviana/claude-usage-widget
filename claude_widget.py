import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as AppIndicator

import os
import threading
import time
from curl_cffi import requests
from datetime import datetime

import claude_config as cfg
from claude_cookies import get_claude_cookies

REFRESH_INTERVAL = 300  # 5 minutos
APP_ID = 'claude-widget'
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'claude-icon.png')


def _fmt_credits(n):
    n = float(n)
    if n < 1000:
        return f"{n:.0f}"
    suffix = 'k' if n < 1_000_000 else 'M'
    v = n / (1000 if suffix == 'k' else 1_000_000)
    s = f"{v:.1f}".rstrip('0').rstrip('.')
    return f"{s}{suffix}"


class ClaudeIndicator:
    def __init__(self):
        icon = ICON_PATH if os.path.exists(ICON_PATH) else 'utilities-system-monitor'
        self.indicator = AppIndicator.Indicator.new(
            APP_ID,
            icon,
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_label('carregando…', '')

        self._build_menu()
        self.indicator.set_menu(self.menu)

        threading.Thread(target=self._fetch_loop, daemon=True).start()

    def _build_menu(self):
        self.menu = Gtk.Menu()

        self.item_5h = Gtk.MenuItem(label='5h: –')
        self.item_5h.set_sensitive(False)
        self.menu.append(self.item_5h)

        self.item_7d = Gtk.MenuItem(label='7d: –')
        self.item_7d.set_sensitive(False)
        self.menu.append(self.item_7d)

        self.item_extra = Gtk.MenuItem(label='extra: –')
        self.item_extra.set_sensitive(False)
        self.menu.append(self.item_extra)

        self.menu.append(Gtk.SeparatorMenuItem())

        self.item_reset = Gtk.MenuItem(label='reset: –')
        self.item_reset.set_sensitive(False)
        self.menu.append(self.item_reset)

        self.item_status = Gtk.MenuItem(label='—')
        self.item_status.set_sensitive(False)
        self.menu.append(self.item_status)

        self.menu.append(Gtk.SeparatorMenuItem())

        refresh = Gtk.MenuItem(label='Atualizar agora')
        refresh.connect('activate', self._on_refresh)
        self.menu.append(refresh)

        quit_item = Gtk.MenuItem(label='Sair')
        quit_item.connect('activate', self._on_quit)
        self.menu.append(quit_item)

        self.menu.show_all()

    def _fetch(self):
        try:
            cookies = get_claude_cookies()
            org_id = cookies.get('lastActiveOrg')
            r = requests.get(
                f'https://claude.ai/api/organizations/{org_id}/usage',
                headers=cfg.HEADERS,
                cookies=cookies,
                impersonate='firefox133',
                timeout=10,
            )
            if r.status_code == 403 and 'Just a moment' in r.text:
                return None, 'bloqueado pelo Cloudflare — abra claude.ai no Firefox'
            r.raise_for_status()
            return r.json(), None
        except Exception as exc:
            return None, str(exc)

    def _fetch_loop(self):
        while True:
            data, err = self._fetch()
            GLib.idle_add(self._update_ui, data, err)
            time.sleep(REFRESH_INTERVAL)

    def _on_refresh(self, _item):
        GLib.idle_add(self.item_status.set_label, 'atualizando…')
        threading.Thread(target=self._refresh_once, daemon=True).start()

    def _refresh_once(self):
        data, err = self._fetch()
        GLib.idle_add(self._update_ui, data, err)

    def _on_quit(self, _item):
        Gtk.main_quit()

    def _update_ui(self, data, err):
        if err or not data:
            msg = (err or 'sem dados')[:40]
            self.indicator.set_label('Claude: erro', '')
            self.item_status.set_label(f'erro: {msg}')
            return False

        five_h = data.get('five_hour') or {}
        seven_d = data.get('seven_day') or {}
        extra = data.get('extra_usage') or {}

        pct_5h = five_h.get('utilization') or 0
        pct_7d = seven_d.get('utilization') or 0

        extra_enabled = bool(extra and extra.get('is_enabled'))
        pct_extra = (extra.get('utilization') or 0) if extra_enabled else 0
        if extra_enabled:
            used = (extra.get('used_credits') or 0) / 100
            limit = (extra.get('monthly_limit') or 0) / 100
            currency = extra.get('currency') or ''
            symbol = '$' if currency == 'USD' else ''
            extra_label_bar = f'{symbol}{_fmt_credits(used)}/{symbol}{_fmt_credits(limit)}'
            extra_label_menu = f'extra: {symbol}{used:,.2f} / {symbol}{limit:,.2f} ({pct_extra:.1f}%)'
        else:
            extra_label_bar = ''
            extra_label_menu = 'extra: desabilitado'

        parts = []
        if pct_5h > 0:
            parts.append(f'5h:{pct_5h:.0f}%')
        if pct_7d > 0:
            parts.append(f'7d:{pct_7d:.0f}%')
        if pct_extra > 0:
            parts.append(extra_label_bar)
        bar_label = ' '.join(parts) if parts else 'Claude: idle'
        self.indicator.set_label(bar_label, '')

        self.item_5h.set_label(self._detail_label('5h', five_h))
        self.item_7d.set_label(self._detail_label('7d', seven_d))
        self.item_extra.set_label(extra_label_menu)

        resets_at = five_h.get('resets_at') or seven_d.get('resets_at')
        if resets_at:
            dt = datetime.fromisoformat(resets_at.replace('Z', '+00:00'))
            local = dt.astimezone()
            self.item_reset.set_label(f"reset: {local.strftime('%d/%m %H:%M')}")
        else:
            self.item_reset.set_label('reset: –')

        self.item_status.set_label(f"atualizado {datetime.now().strftime('%H:%M')}")
        return False

    def _detail_label(self, prefix, window):
        pct = window.get('utilization') or 0
        used = window.get('used_credits')
        limit = window.get('credit_limit')
        if used is not None and limit:
            return f'{prefix}: {pct:.1f}% ({_fmt_credits(used)}/{_fmt_credits(limit)})'
        return f'{prefix}: {pct:.1f}%'


if __name__ == '__main__':
    ClaudeIndicator()
    Gtk.main()
