import os
from datetime import datetime

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from curl_cffi import requests

import claude_config as cfg
from claude_auth import get_oauth_token, get_credentials_path, TokenMissing, TokenExpired
from claude_cookies import get_claude_cookies, cookies_available

from .base import BarItem, Provider, ProviderResult


_ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'claude-icon.png',
)


def _fmt_credits(n):
    n = float(n)
    if n < 1000:
        return f"{n:.0f}"
    suffix = 'k' if n < 1_000_000 else 'M'
    v = n / (1000 if suffix == 'k' else 1_000_000)
    s = f"{v:.1f}".rstrip('0').rstrip('.')
    return f"{s}{suffix}"


class ClaudeUsageProvider(Provider):
    name = 'claude'
    refresh_interval = 300  # 5 minutos

    @staticmethod
    def _is_available() -> bool:
        """Há alguma credencial Claude acessível?"""
        if os.path.exists(get_credentials_path()):
            return True
        return cookies_available()

    def icon_path(self, result: ProviderResult) -> str | None:
        return _ICON_PATH if os.path.exists(_ICON_PATH) else None

    def _fetch_oauth(self):
        token = get_oauth_token()
        r = requests.get(
            cfg.OAUTH_USAGE_URL,
            headers={**cfg.OAUTH_HEADERS, 'Authorization': f'Bearer {token}'},
            impersonate='firefox133',
            timeout=10,
        )
        if r.status_code in (401, 403):
            raise TokenExpired(f'auth rejeitada (HTTP {r.status_code}) — rode `claude` para renovar')
        r.raise_for_status()
        return r.json()

    def _fetch_cookies(self):
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
            raise RuntimeError('bloqueado pelo Cloudflare — abra claude.ai no Firefox')
        r.raise_for_status()
        return r.json()

    def fetch(self) -> ProviderResult:
        if not self._is_available():
            # Sem credenciais — provider fica inativo (não polui a barra/menu)
            return ProviderResult()

        oauth_err = None
        try:
            return ProviderResult(data=self._fetch_oauth())
        except (TokenMissing, TokenExpired) as exc:
            oauth_err = str(exc)
        except Exception as exc:
            oauth_err = f'oauth: {exc}'

        try:
            return ProviderResult(data=self._fetch_cookies())
        except Exception as exc:
            return ProviderResult(error=f'{oauth_err}; cookies: {exc}')

    def _extract(self, data):
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
            sep = ' ' if symbol else ''
            extra_bar = f'{symbol}{sep}{_fmt_credits(used)}/{_fmt_credits(limit)}'
            extra_menu = f'extra: {symbol}{sep}{used:,.2f} / {limit:,.2f} ({pct_extra:.1f}%)'
        else:
            extra_bar = ''
            extra_menu = 'extra: desabilitado'

        return {
            'five_h': five_h, 'seven_d': seven_d, 'extra': extra,
            'pct_5h': pct_5h, 'pct_7d': pct_7d, 'pct_extra': pct_extra,
            'extra_bar': extra_bar, 'extra_menu': extra_menu,
        }

    def items(self, result: ProviderResult) -> list[BarItem]:
        if not self._is_available():
            return []
        return super().items(result)

    def render_bar(self, result: ProviderResult) -> str | None:
        if not self._is_available():
            return None
        if result.error or not result.data:
            return 'Claude: erro'

        v = self._extract(result.data)
        parts = []
        if v['pct_5h'] > 0:
            parts.append(f"5h:{v['pct_5h']:.0f}%")
        if v['pct_7d'] > 0:
            parts.append(f"7d:{v['pct_7d']:.0f}%")
        if v['pct_extra'] > 0:
            parts.append(v['extra_bar'])
        return ' '.join(parts) if parts else 'Claude: idle'

    def menu_header(self, result: ProviderResult) -> str | None:
        if not self._is_available():
            return None
        bar = self.render_bar(result)
        return f'Claude — {bar}' if bar else 'Claude'

    def render_menu(self, result: ProviderResult) -> list:
        if not self._is_available():
            return []

        items = []

        if result.error or not result.data:
            msg = (result.error or 'sem dados')[:60]
            items.append(self._sensitive_item(f'erro: {msg}'))
            return items

        v = self._extract(result.data)

        items.append(self._sensitive_item(self._detail_label('5h', v['five_h'])))
        items.append(self._sensitive_item(self._detail_label('7d', v['seven_d'])))
        items.append(self._sensitive_item(v['extra_menu']))

        items.append(Gtk.SeparatorMenuItem())

        resets_at = v['five_h'].get('resets_at') or v['seven_d'].get('resets_at')
        if resets_at:
            dt = datetime.fromisoformat(resets_at.replace('Z', '+00:00'))
            local = dt.astimezone()
            items.append(self._sensitive_item(f"reset: {local.strftime('%d/%m %H:%M')}"))
        else:
            items.append(self._sensitive_item('reset: –'))

        items.append(self._sensitive_item(
            f"atualizado {datetime.now().strftime('%H:%M')}"
        ))

        return items

    @staticmethod
    def _sensitive_item(label):
        item = Gtk.MenuItem(label=label)
        item.set_sensitive(False)
        return item

    @staticmethod
    def _detail_label(prefix, window):
        pct = window.get('utilization') or 0
        used = window.get('used_credits')
        limit = window.get('credit_limit')
        if used is not None and limit:
            return f'{prefix}: {pct:.1f}% ({_fmt_credits(used)}/{_fmt_credits(limit)})'
        return f'{prefix}: {pct:.1f}%'
