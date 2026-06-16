"""Provider de futebol — placares de clubes monitorados + Copa do Mundo.

Fontes (o Sofascore parou: passou a exigir desafio Cloudflare/cf_clearance):

- **FIFA** (`api.fifa.com/api/v3`, keyless, em pt-BR): a Copa do Mundo vem do
  `calendar/matches` (competição 17) — nomes em português, placar, status e
  bandeiras. O `live/football/now` é usado como overlay de placar/minuto ao
  vivo dos clubes monitorados.
- **TheSportsDB** (chave free "3"): agenda/resultados dos clubes via
  `searchteams`/`eventsnext`/`eventslast`, com escudos por URL.

O resto do widget consome `items()`/`menu_*()` como antes — só a fonte mudou.
"""

import os
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from curl_cffi import requests

import widget_settings

from . import _format
from .base import BarItem, MENU_SEPARATOR, Provider, ProviderResult


TSDB_BASE = 'https://www.thesportsdb.com/api/v1/json/3'
FIFA_BASE = 'https://api.fifa.com/api/v3'
FIFA_LIVE_URL = f'{FIFA_BASE}/live/football/now?language=pt-BR'
FIFA_LANG = 'pt-BR'

# Competição "Copa do Mundo da FIFA" na API da FIFA (id numérico estável).
# Sobrescrevível via config (world_cup_id).
WORLD_CUP_COMPETITION_ID = '17'

# Cadências de polling em segundos
REFRESH_LIVE = 60            # algum jogo ao vivo
REFRESH_PREGAME_SOON = 120   # jogo começa em < 30 min
REFRESH_IDLE = 600           # nada acontecendo

PREGAME_SOON_WINDOW = 30 * 60  # 30 minutos
SHOW_UPCOMING_WINDOW = 7 * 24 * 3600  # só mostra jogos futuros dentro de 1 semana

_CACHE_DIR = os.path.expanduser('~/.cache/claude-widget')

# Status da TheSportsDB que mapeiam pra "não começou" / "encerrado"
_UPCOMING_STATUS = {'', 'NS', 'Not Started', 'TBD', 'Postponed', 'Cancelled'}
_FINISHED_STATUS = {
    'FT', 'Match Finished', 'AET', 'After Extra Time', 'PEN', 'Penalties', 'AP',
}

# Cache name→time (TheSportsDB) por processo, evita refazer searchteams toda hora
_TEAM_CACHE: dict[str, dict | None] = {}


# ---------- helpers de rede ----------

def _http_json(url: str) -> dict | None:
    try:
        r = requests.get(url, impersonate='firefox133', timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _download_badge(url: str | None) -> str | None:
    """Baixa/cacheia um escudo/bandeira a partir de uma URL (TheSportsDB ou FIFA)."""
    if not url:
        return None
    # chave de cache única por URL (URLs da FIFA não têm nome de arquivo)
    key = ''.join(c if c.isalnum() else '-' for c in url.split('//', 1)[-1])[-80:]
    path = os.path.join(_CACHE_DIR, f'badge-{key}.png')
    if os.path.exists(path):
        return path
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        r = requests.get(url, impersonate='firefox133', timeout=10)
        r.raise_for_status()
        with open(path, 'wb') as f:
            f.write(r.content)
        return path
    except Exception:
        return None


# ---------- helpers de parsing ----------

def _norm(s: str | None) -> str:
    """Normaliza nome de time pra casar fontes diferentes: sem acento, só
    alfanumérico minúsculo (`Avaí` → `avai`)."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ''.join(c for c in s.lower() if c.isalnum())


def _to_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_when(epoch: float | None) -> str:
    if not epoch:
        return ''
    local = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone()
    return _format.format_when(local, include_time=True)


def _is_today(epoch: float) -> bool:
    local = datetime.fromtimestamp(epoch).astimezone()
    today = datetime.now().astimezone().date()
    return local.date() == today


def _league_label(name: str | None) -> str:
    name = (name or '').replace('™', '').strip()
    # "Copa do Mundo da FIFA" / "FIFA World Cup" → "Copa do Mundo"
    if 'Copa do Mundo' in name or 'World Cup' in name:
        return 'Copa do Mundo'
    return name


def _classify(status_raw: str) -> str:
    if status_raw in _FINISHED_STATUS:
        return 'finished'
    if status_raw in _UPCOMING_STATUS:
        return 'upcoming'
    return 'live'


def _fifa_team_name(team: dict | None) -> str:
    if not team:
        return ''
    names = team.get('TeamName') or []
    if names:
        return names[0].get('Description') or ''
    return team.get('ShortClubName') or ''


def _fifa_live_index() -> dict:
    """Índice dos jogos ao vivo da FIFA, chaveado pelo par de times
    normalizado → {hs, as_, minute}. Usado pra enriquecer placar/minuto."""
    data = _http_json(FIFA_LIVE_URL)
    idx: dict = {}
    for m in (data or {}).get('Results') or []:
        home = _fifa_team_name(m.get('HomeTeam'))
        away = _fifa_team_name(m.get('AwayTeam'))
        if not home or not away:
            continue
        idx[frozenset((_norm(home), _norm(away)))] = {
            'hs': (m.get('HomeTeam') or {}).get('Score'),
            'as_': (m.get('AwayTeam') or {}).get('Score'),
            'minute': (m.get('MatchTime') or '').strip() or None,
        }
    return idx


def _fifa_loc(field) -> str:
    """Extrai a Description pt-BR de um campo localizado da FIFA (lista de
    {Locale, Description})."""
    if isinstance(field, list) and field:
        return field[0].get('Description') or ''
    return field or ''


def _fifa_picture(team: dict | None) -> str | None:
    """URL da bandeira/escudo da FIFA, resolvendo o template PictureUrl
    (`.../flags-{format}-{size}/SWE` → `.../flags-sq-4/SWE`)."""
    url = (team or {}).get('PictureUrl')
    if not url:
        return None
    return url.replace('{format}', 'sq').replace('{size}', '4')


def _match_from_fifa(m: dict) -> dict:
    """Normaliza um jogo do `calendar/matches` da FIFA (já em pt-BR)."""
    home = m.get('Home') or {}
    away = m.get('Away') or {}
    hs = home.get('Score')
    as_ = away.get('Score')
    status = m.get('MatchStatus')
    start = _parse_ts(m.get('Date'))

    if status == 3:
        state = 'live'
        minute = (m.get('MatchTime') or '').strip() or 'ao vivo'
    elif hs is not None and as_ is not None:
        state = 'finished'
        minute = None
    else:
        state = 'upcoming'
        minute = None

    return {
        'home': _fifa_team_name(home), 'away': _fifa_team_name(away),
        'home_badge': _download_badge(_fifa_picture(home)),
        'away_badge': _download_badge(_fifa_picture(away)),
        'hs': hs, 'as_': as_,
        'state': state, 'minute': minute,
        'start': start.timestamp() if start else None,
        'league': _league_label(_fifa_loc(m.get('CompetitionName'))),
        'pin_id': None,
    }


def _match_from_tsdb(ev: dict, live_idx: dict, pin_id: str | None = None) -> dict:
    """Normaliza um evento da TheSportsDB no dict de match usado pelo widget,
    enriquecendo placar/minuto pela FIFA quando o jogo está ao vivo."""
    home = ev.get('strHomeTeam') or '?'
    away = ev.get('strAwayTeam') or '?'
    status_raw = (ev.get('strStatus') or '').strip()
    state = _classify(status_raw)
    hs = _to_int(ev.get('intHomeScore'))
    as_ = _to_int(ev.get('intAwayScore'))
    start_dt = _parse_ts(ev.get('strTimestamp'))
    minute = None

    if state == 'live':
        if status_raw.upper() == 'HT':
            minute = 'HT'
        else:
            prog = (ev.get('strProgress') or '').strip()
            minute = f"{prog}'" if prog.isdigit() else (status_raw or None)
        fifa = live_idx.get(frozenset((_norm(home), _norm(away))))
        if fifa:
            if fifa['hs'] is not None:
                hs = fifa['hs']
            if fifa['as_'] is not None:
                as_ = fifa['as_']
            if fifa['minute']:
                minute = fifa['minute']

    return {
        'home': home, 'away': away,
        'home_badge': _download_badge(ev.get('strHomeTeamBadge')),
        'away_badge': _download_badge(ev.get('strAwayTeamBadge')),
        'hs': hs, 'as_': as_,
        'state': state, 'minute': minute,
        'start': start_dt.timestamp() if start_dt else None,
        'league': _league_label(ev.get('strLeague')),
        'pin_id': pin_id,
    }


def _pair(m: dict) -> frozenset:
    return frozenset((_norm(m['home']), _norm(m['away'])))


# ---------- render (match dict → BarItem / linha de menu) ----------

def _bar_item(m: dict) -> BarItem:
    home, away = m['home'], m['away']
    if m['state'] == 'live':
        core = f"{home} {m['hs'] or 0}x{m['as_'] or 0} {away}"
        tail = m['minute'] or 'ao vivo'
    elif m['state'] == 'finished':
        core = f"{home} {m['hs'] or 0}x{m['as_'] or 0} {away}"
        tail = 'FT'
    else:
        core = f'{home} x {away}'
        tail = _format_when(m['start'])
    label = f'{core} {tail}'.strip()
    if m['league']:
        label = f"{label} · {m['league']}"
    return BarItem(
        label=label,
        icon_path=m['home_badge'], icon_right_path=m['away_badge'],
        label_core=core, label_tail=tail, pin_id=m['pin_id'],
    )


def _menu_line(m: dict) -> str:
    if m['state'] == 'live':
        return f"{m['home']} {m['hs'] or 0}x{m['as_'] or 0} {m['away']}  ({m['minute'] or 'ao vivo'})"
    if m['state'] == 'finished':
        return f"{m['home']} {m['hs'] or 0}x{m['as_'] or 0} {m['away']}  (FT)"
    when = _format_when(m['start']) or '?'
    return f"{m['home']} x {m['away']}  ({when})"


# ---------- provider ----------

class FootballProvider(Provider):
    name = 'football'
    refresh_interval = REFRESH_IDLE  # fallback; uso real via next_refresh_seconds()

    def __init__(self):
        self._next_refresh = REFRESH_IDLE
        self._config = self._load_config()

    @staticmethod
    def _load_config() -> dict:
        return widget_settings.load().get('football', {}) or {}

    def _resolve_team(self, name: str) -> dict | None:
        if name in _TEAM_CACHE:
            return _TEAM_CACHE[name]
        data = _http_json(f'{TSDB_BASE}/searchteams.php?t={quote(name)}')
        teams = (data or {}).get('teams') or []
        result = teams[0] if teams else None
        _TEAM_CACHE[name] = result
        return result

    def _club_match(self, name: str, live_idx: dict) -> dict | None:
        team = self._resolve_team(name)
        if not team:
            return None
        tid = team.get('idTeam')
        pin_id = f'football:team:{_norm(name)}'

        # próximo jogo (inclui o que está em andamento, com status tipo "1H")
        data = _http_json(f'{TSDB_BASE}/eventsnext.php?id={tid}')
        events = (data or {}).get('events') or []
        ev = events[0] if events else None
        if ev is None:
            return None

        m = _match_from_tsdb(ev, live_idx, pin_id=pin_id)
        # jogo futuro a mais de 1 semana → não exibe
        if m['state'] == 'upcoming' and m['start']:
            if m['start'] - time.time() > SHOW_UPCOMING_WINDOW:
                return None
        # jogo encerrado: exibe só se foi hoje
        if m['state'] == 'finished':
            if not m['start'] or not _is_today(m['start']):
                return None
        # fallback de escudo: usa o badge do time monitorado se o evento não trouxe
        team_badge = _download_badge(team.get('strBadge'))
        if _norm(m['home']) == _norm(team.get('strTeam') or name):
            m['home_badge'] = m['home_badge'] or team_badge
        else:
            m['away_badge'] = m['away_badge'] or team_badge
        return m

    def _world_cup_today(self) -> list[dict]:
        """Jogos da Copa do Mundo de HOJE (horário local), via FIFA em pt-BR —
        ao vivo, agendados e encerrados, ordenados por horário."""
        comp_id = str(self._config.get('world_cup_id') or WORLD_CUP_COMPETITION_ID)
        # janela do dia local convertida pra UTC (a FIFA filtra por Date UTC)
        now_local = datetime.now().astimezone()
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        frm = start_local.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        to = end_local.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        url = (
            f'{FIFA_BASE}/calendar/matches?language={FIFA_LANG}'
            f'&idCompetition={comp_id}&count=100&from={frm}&to={to}'
        )
        data = _http_json(url)
        matches = []
        for m in (data or {}).get('Results') or []:
            dt = _parse_ts(m.get('Date'))
            # garante que cai no dia local (a FIFA é inclusiva nas bordas)
            if dt and start_local <= dt.astimezone() < end_local:
                matches.append(_match_from_fifa(m))
        matches.sort(key=lambda x: x['start'] or 0)
        return matches

    def fetch(self) -> ProviderResult:
        self._config = self._load_config()
        teams = self._config.get('teams') or []
        world_cup = bool(self._config.get('world_cup'))

        if not teams and not world_cup:
            self._next_refresh = REFRESH_IDLE
            return ProviderResult()

        live_idx = _fifa_live_index()

        club: list[dict] = []
        for team in teams:
            tname = team.get('name') if isinstance(team, dict) else team
            if not tname:
                continue
            try:
                m = self._club_match(tname, live_idx)
            except Exception:
                m = None
            if m:
                club.append(m)

        wc = self._world_cup_today() if world_cup else []

        self._next_refresh = self._refresh_for(club + wc)
        return ProviderResult(data={'club': club, 'wc': wc})

    def next_refresh_seconds(self) -> int:
        return self._next_refresh

    @staticmethod
    def _refresh_for(matches: list[dict]) -> int:
        soonest = None
        for m in matches:
            if m['state'] == 'live':
                return REFRESH_LIVE
            if m['state'] == 'upcoming' and m['start']:
                delta = m['start'] - time.time()
                if 0 < delta < PREGAME_SOON_WINDOW:
                    soonest = min(soonest, delta) if soonest else delta
        if soonest is not None:
            return REFRESH_PREGAME_SOON
        return REFRESH_IDLE

    def items(self, result: ProviderResult) -> list[BarItem]:
        if result.error or not result.data:
            return []
        club = result.data.get('club') or []
        wc = result.data.get('wc') or []
        club_pairs = {_pair(m) for m in club}
        all_matches = list(club) + [m for m in wc if _pair(m) not in club_pairs]
        if any(m['state'] == 'live' for m in all_matches):
            all_matches = [m for m in all_matches if m['state'] == 'live']
        return [_bar_item(m) for m in all_matches]

    def menu_header(self, result: ProviderResult) -> str | None:
        if not result.data and not result.error:
            return None
        if result.error:
            return 'Futebol — erro'
        data = result.data or {}
        club = data.get('club') or []
        wc = data.get('wc') or []
        parts = []
        if club:
            parts.append(f'{len(club)} time' if len(club) == 1 else f'{len(club)} times')
        if wc:
            wc_live = sum(1 for m in wc if m['state'] == 'live')
            parts.append(f'Copa: {wc_live} ao vivo' if wc_live else f'Copa: {len(wc)} hoje')
        return f"Futebol · {' · '.join(parts)}" if parts else None

    def render_menu(self, result: ProviderResult) -> list:
        if result.error:
            return [f'erro: {result.error[:60]}']
        data = result.data or {}
        club = data.get('club') or []
        wc = data.get('wc') or []

        items = [_menu_line(m) for m in club]

        club_pairs = {_pair(m) for m in club}
        wc = [m for m in wc if _pair(m) not in club_pairs]
        if wc:
            if items:
                items.append(MENU_SEPARATOR)
            items.append('Copa do Mundo:')
            for m in wc:
                items.append('   ' + _menu_line(m))
        return items
