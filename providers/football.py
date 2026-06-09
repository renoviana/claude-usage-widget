import math
import os
import time
from datetime import datetime, timezone

from curl_cffi import requests

import widget_settings

from . import _format
from .base import BarItem, MENU_SEPARATOR, Provider, ProviderResult


SOFASCORE_BASE = 'https://api.sofascore.com/api/v1'

_CACHE_DIR = os.path.expanduser('~/.cache/claude-widget')

# Cadências de polling em segundos
REFRESH_LIVE = 60            # algum jogo monitorado/ao vivo está rolando
REFRESH_PREGAME_SOON = 120   # jogo monitorado começa em < 30 min
REFRESH_IDLE = 600           # nada acontecendo


def _live_minute(event: dict) -> int | None:
    """Calcula o minuto da partida a partir do bloco `time` do Sofascore."""
    t = event.get('time') or {}
    start_ts = t.get('currentPeriodStartTimestamp')
    initial = t.get('initial') or 0
    if not start_ts:
        return None
    elapsed = time.time() - start_ts + initial
    if elapsed < 0:
        return None
    return max(1, math.ceil(elapsed / 60))


def _team_logo_path(team_id: int) -> str:
    return os.path.join(_CACHE_DIR, f'team-{team_id}.png')


def _download_team_logo(team_id: int) -> str | None:
    path = _team_logo_path(team_id)
    if os.path.exists(path):
        return path
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        r = requests.get(
            f'{SOFASCORE_BASE}/team/{team_id}/image',
            impersonate='firefox133',
            timeout=10,
        )
        r.raise_for_status()
        with open(path, 'wb') as f:
            f.write(r.content)
        return path
    except Exception:
        return None


def _event_logos(event: dict) -> tuple[str | None, str | None]:
    """(escudo da casa, escudo do visitante) de um jogo — baixados/cacheados."""
    home_id = (event.get('homeTeam') or {}).get('id')
    away_id = (event.get('awayTeam') or {}).get('id')
    home = _download_team_logo(home_id) if home_id else None
    away = _download_team_logo(away_id) if away_id else None
    return home, away


def _team_name(team: dict) -> str:
    return team.get('shortName') or team.get('name') or '?'


def _format_when(start_ts: float) -> str:
    local = datetime.fromtimestamp(start_ts, tz=timezone.utc).astimezone()
    return _format.format_when(local, include_time=True)


_TOURNAMENT_PREFIXES = ('CONMEBOL ', 'UEFA ', 'AFC ', 'CONCACAF ', 'CAF ')
_TOURNAMENT_SUFFIXES = (' Betano', ' EA Sports', ' Assaí')


def _tournament(event: dict) -> str:
    t = event.get('tournament') or {}
    name = (t.get('uniqueTournament') or {}).get('name') or t.get('name') or ''
    # corta o que vier após a primeira vírgula ("Group H", "Série B", "Knockout Stage", ...)
    name = name.split(',', 1)[0].strip()
    for p in _TOURNAMENT_PREFIXES:
        if name.startswith(p):
            name = name[len(p):]
            break
    for s in _TOURNAMENT_SUFFIXES:
        if name.endswith(s):
            name = name[: -len(s)]
            break
    return name.strip()


def _with_tournament(label: str, event: dict) -> str:
    tour = _tournament(event)
    return f'{label} · {tour}' if tour else label


# Nota: o nome do torneio NÃO entra no `label_tail` (pílula do Windows) de
# propósito — quem fixa um torneio já sabe qual é, e repeti-lo em cada jogo
# alargava demais a janela. Ele continua no `label` completo (GTK/bandeja) e
# no menu de detalhes.


def _format_team_match(team_id: int, event: dict) -> str:
    """Label do jogo do POV de um time monitorado (placar dele primeiro)."""
    home = event.get('homeTeam') or {}
    away = event.get('awayTeam') or {}
    if home.get('id') == team_id:
        opp = away
        own_score = (event.get('homeScore') or {}).get('current') or 0
        opp_score = (event.get('awayScore') or {}).get('current') or 0
    else:
        opp = home
        own_score = (event.get('awayScore') or {}).get('current') or 0
        opp_score = (event.get('homeScore') or {}).get('current') or 0
    opp_name = _team_name(opp)
    status = (event.get('status') or {}).get('type')

    if status == 'inprogress':
        desc = (event.get('status') or {}).get('description') or ''
        if desc.lower() == 'halftime':
            tag = 'HT'
        else:
            minute = _live_minute(event)
            tag = f"{minute}'" if minute is not None else desc
        return _with_tournament(f'{own_score}x{opp_score} vs {opp_name} {tag}', event)

    if status == 'finished':
        return _with_tournament(f'{own_score}x{opp_score} vs {opp_name} FT', event)

    start = event.get('startTimestamp')
    if start:
        return _with_tournament(f'vs {opp_name} {_format_when(start)}', event)
    return _with_tournament(f'vs {opp_name}', event)


def _upcoming_parts(event: dict) -> tuple[str, str]:
    """(core, tail) de um jogo que ainda não começou (modo torneio).

    core = `Casa x Fora` (escudo do visitante vai logo após); tail = horário +
    torneio.
    """
    home = _team_name(event.get('homeTeam') or {})
    away = _team_name(event.get('awayTeam') or {})
    start = event.get('startTimestamp')
    when = _format_when(start) if start else ''
    return f'{home} x {away}', when


def _format_upcoming_event(event: dict) -> str:
    """Label COMPLETO — usado por frontends de um ícone só (GTK/bandeja)."""
    home = _team_name(event.get('homeTeam') or {})
    away = _team_name(event.get('awayTeam') or {})
    start = event.get('startTimestamp')
    when = _format_when(start) if start else ''
    label = f'{home} x {away}'
    if when:
        label = f'{label} {when}'
    return _with_tournament(label, event)


def _event_tournament_id(event: dict):
    t = event.get('tournament') or {}
    ut = t.get('uniqueTournament') or {}
    return ut.get('id') or t.get('id')


def _live_parts(event: dict) -> tuple[str, str]:
    """(core, tail) de um jogo ao vivo.

    core = `Casa 1x0 Fora` (escudo do visitante vai logo após `Fora`);
    tail = minuto/status + torneio.
    """
    home = _team_name(event.get('homeTeam') or {})
    away = _team_name(event.get('awayTeam') or {})
    hs = (event.get('homeScore') or {}).get('current') or 0
    as_ = (event.get('awayScore') or {}).get('current') or 0
    desc = (event.get('status') or {}).get('description') or ''
    if desc.lower() == 'halftime':
        tag = 'HT'
    else:
        minute = _live_minute(event)
        tag = f"{minute}'" if minute is not None else desc
    return f'{home} {hs}x{as_} {away}', tag


def _format_live_event(event: dict) -> str:
    """Label genérico pra jogo ao vivo no feed global (texto COMPLETO)."""
    home = _team_name(event.get('homeTeam') or {})
    away = _team_name(event.get('awayTeam') or {})
    hs = (event.get('homeScore') or {}).get('current') or 0
    as_ = (event.get('awayScore') or {}).get('current') or 0
    desc = (event.get('status') or {}).get('description') or ''
    if desc.lower() == 'halftime':
        tag = 'HT'
    else:
        minute = _live_minute(event)
        tag = f"{minute}'" if minute is not None else desc
    return _with_tournament(f'{home} {hs}x{as_} {away} {tag}', event)


class FootballProvider(Provider):
    name = 'football'
    refresh_interval = REFRESH_IDLE  # fallback; uso real é via next_refresh_seconds()

    PREGAME_SOON_WINDOW = 30 * 60  # 30 minutos

    def __init__(self):
        self._next_refresh = REFRESH_IDLE
        self._config = self._load_config()

    @staticmethod
    def _load_config() -> dict:
        return widget_settings.load().get('football', {}) or {}

    def _team_event(self, team_id: int) -> dict | None:
        try:
            r = requests.get(
                f'{SOFASCORE_BASE}/team/{team_id}/events/next/0',
                impersonate='firefox133',
                timeout=10,
            )
            r.raise_for_status()
            events = r.json().get('events') or []
        except Exception:
            return None
        if not events:
            return None
        # /next/0 inclui jogo em andamento; preferir esse.
        live = next(
            (e for e in events if (e.get('status') or {}).get('type') == 'inprogress'),
            None,
        )
        return live or events[0]

    def _live_events(self) -> list[dict]:
        try:
            r = requests.get(
                f'{SOFASCORE_BASE}/sport/football/events/live',
                impersonate='firefox133',
                timeout=10,
            )
            r.raise_for_status()
            return r.json().get('events') or []
        except Exception:
            return []

    def _tournament_upcoming(self, tournament_id, season_id) -> list[dict]:
        """Próximos jogos de um torneio/temporada (events/next/0)."""
        if not tournament_id or not season_id:
            return []
        try:
            r = requests.get(
                f'{SOFASCORE_BASE}/unique-tournament/{tournament_id}'
                f'/season/{season_id}/events/next/0',
                impersonate='firefox133',
                timeout=10,
            )
            r.raise_for_status()
            return r.json().get('events') or []
        except Exception:
            return []

    def fetch(self) -> ProviderResult:
        self._config = self._load_config()
        teams = self._config.get('teams') or []
        tournaments = self._config.get('tournaments') or []
        live_on = bool(self._config.get('live_matches'))

        # Sem nada configurado → fica inativo
        if not teams and not tournaments and not live_on:
            self._next_refresh = REFRESH_IDLE
            return ProviderResult()

        # Prioridade: feed global ao vivo > torneios > times monitorados
        if live_on:
            events = self._live_events()
            self._next_refresh = REFRESH_LIVE if events else REFRESH_IDLE
            return ProviderResult(data={'mode': 'live', 'events': events})

        if tournaments:
            tids = {t['id'] for t in tournaments if t.get('id') is not None}
            live = [
                e for e in self._live_events()
                if _event_tournament_id(e) in tids
            ]
            upcoming = []
            for t in tournaments:
                upcoming.extend(
                    self._tournament_upcoming(t.get('id'), t.get('season'))
                )
            upcoming = [
                e for e in upcoming
                if (e.get('status') or {}).get('type') == 'notstarted'
            ]
            upcoming.sort(key=lambda e: e.get('startTimestamp') or 0)
            self._next_refresh = self._compute_tournament_refresh(live, upcoming)
            return ProviderResult(
                data={'mode': 'tournaments', 'live': live, 'upcoming': upcoming}
            )

        team_events = {}
        for team in teams:
            team_events[team['id']] = self._team_event(team['id'])
        self._next_refresh = self._compute_idle_refresh(team_events)
        return ProviderResult(data={'mode': 'teams', 'team_events': team_events})

    def next_refresh_seconds(self) -> int:
        return self._next_refresh

    def _compute_tournament_refresh(self, live: list, upcoming: list) -> int:
        if live:
            return REFRESH_LIVE
        # upcoming já vem ordenado por horário; basta olhar o mais próximo
        for event in upcoming:
            delta = (event.get('startTimestamp') or 0) - time.time()
            if 0 < delta < self.PREGAME_SOON_WINDOW:
                return REFRESH_PREGAME_SOON
            if delta > 0:
                break
        return REFRESH_IDLE

    def _compute_idle_refresh(self, team_events: dict) -> int:
        any_live = False
        soonest_pregame = None
        for event in team_events.values():
            if not event:
                continue
            status = (event.get('status') or {}).get('type')
            if status == 'inprogress':
                any_live = True
                break
            start = event.get('startTimestamp') or 0
            delta = start - time.time()
            if 0 < delta < self.PREGAME_SOON_WINDOW:
                soonest_pregame = min(soonest_pregame, delta) if soonest_pregame else delta
        if any_live:
            return REFRESH_LIVE
        if soonest_pregame is not None:
            return REFRESH_PREGAME_SOON
        return REFRESH_IDLE

    @staticmethod
    def _live_bar_item(event: dict) -> BarItem:
        """BarItem de um jogo ao vivo, com escudo da casa à esq. e do
        visitante flanqueando o placar (`🛡️ Casa 1x0 Fora 🛡️ 67' · Torneio`)."""
        home_icon, away_icon = _event_logos(event)
        core, tail = _live_parts(event)
        return BarItem(
            label=_format_live_event(event),
            icon_path=home_icon, icon_right_path=away_icon,
            label_core=core, label_tail=tail, pin_id=None,
        )

    @staticmethod
    def _upcoming_bar_item(event: dict) -> BarItem:
        """BarItem de um jogo futuro (`🛡️ Casa x Fora 🛡️ horário · Torneio`)."""
        home_icon, away_icon = _event_logos(event)
        core, tail = _upcoming_parts(event)
        return BarItem(
            label=_format_upcoming_event(event),
            icon_path=home_icon, icon_right_path=away_icon,
            label_core=core, label_tail=tail, pin_id=None,
        )

    def items(self, result: ProviderResult) -> list[BarItem]:
        if result.error or not result.data:
            return []

        if result.data.get('mode') == 'live':
            # itens do feed global não são fixáveis (lista grande, dinâmica)
            events = result.data.get('events') or []
            return [self._live_bar_item(event) for event in events]

        if result.data.get('mode') == 'tournaments':
            live = result.data.get('live') or []
            if live:
                # ao vivo: rotaciona todos os jogos rolando agora
                return [self._live_bar_item(event) for event in live]
            # nada ao vivo: mostra os próximos jogos (cap 3 pra não poluir)
            upcoming = result.data.get('upcoming') or []
            return [self._upcoming_bar_item(event) for event in upcoming[:3]]

        # mode == 'teams'
        team_events = result.data.get('team_events') or {}
        teams = self._config.get('teams') or []
        out = []
        for team in teams:
            event = team_events.get(team['id'])
            if not event:
                continue
            label = _format_team_match(team['id'], event)
            icon = _download_team_logo(team['id'])
            out.append(BarItem(
                label=label,
                icon_path=icon,
                pin_id=f"football:team:{team['id']}",
            ))
        return out

    def menu_header(self, result: ProviderResult) -> str | None:
        # Sem data e sem erro → provider inativo (não configurado)
        if not result.data and not result.error:
            return None
        if result.error:
            return 'Futebol — erro'
        data = result.data or {}
        if data.get('mode') == 'live':
            live_events = data.get('events') or []
            return f'Jogos ao vivo · {len(live_events)}'
        if data.get('mode') == 'tournaments':
            tournaments = self._config.get('tournaments') or []
            names = ', '.join(t.get('name') or '?' for t in tournaments) or 'Torneios'
            live = data.get('live') or []
            upcoming = data.get('upcoming') or []
            if live:
                return f'{names} · {len(live)} ao vivo'
            if upcoming:
                return f'{names} · próx. {len(upcoming)}'
            return f'{names} · sem jogos'
        teams = self._config.get('teams') or []
        if not teams:
            return None
        if len(teams) == 1:
            return f"Futebol · {teams[0]['name']}"
        return f'Futebol · {len(teams)} times'

    def render_menu(self, result: ProviderResult) -> list:
        items = []

        if result.error:
            return [f'erro: {result.error[:60]}']

        data = result.data or {}

        if data.get('mode') == 'live':
            live_events = data.get('events') or []
            for event in live_events[:15]:
                home = _team_name(event.get('homeTeam') or {})
                away = _team_name(event.get('awayTeam') or {})
                hs = (event.get('homeScore') or {}).get('current') or 0
                as_ = (event.get('awayScore') or {}).get('current') or 0
                minute = _live_minute(event)
                tag = f"{minute}'" if minute is not None else (
                    (event.get('status') or {}).get('description') or ''
                )
                items.append(f'{home} {hs}x{as_} {away}  ({tag})')
            if len(live_events) > 15:
                items.append(f'… e mais {len(live_events) - 15}')
            return items

        if data.get('mode') == 'tournaments':
            live = data.get('live') or []
            upcoming = data.get('upcoming') or []
            for event in live[:15]:
                home = _team_name(event.get('homeTeam') or {})
                away = _team_name(event.get('awayTeam') or {})
                hs = (event.get('homeScore') or {}).get('current') or 0
                as_ = (event.get('awayScore') or {}).get('current') or 0
                minute = _live_minute(event)
                tag = f"{minute}'" if minute is not None else (
                    (event.get('status') or {}).get('description') or ''
                )
                items.append(f'{home} {hs}x{as_} {away}  ({tag})')
            if live and upcoming:
                items.append(MENU_SEPARATOR)
            for event in upcoming[:10]:
                home = _team_name(event.get('homeTeam') or {})
                away = _team_name(event.get('awayTeam') or {})
                start = event.get('startTimestamp')
                when = _format_when(start) if start else '?'
                items.append(f'{home} x {away}  ({when})')
            if not items:
                items.append('sem jogos próximos')
            return items

        # mode == 'teams'
        teams = self._config.get('teams') or []
        team_events = data.get('team_events') or {}
        if not teams:
            return items

        for team in teams:
            event = team_events.get(team['id'])
            if not event:
                items.append(f"{team['name']}: sem jogos próximos")
                continue
            items.append(self._format_team_line(team['id'], event))
            tournament = (event.get('tournament') or {}).get('name')
            if tournament:
                items.append(f'   ↳ {tournament}')

        return items

    @staticmethod
    def _format_team_line(team_id: int, event: dict) -> str:
        home_team = event.get('homeTeam') or {}
        away_team = event.get('awayTeam') or {}
        home_full = home_team.get('name') or '?'
        away_full = away_team.get('name') or '?'
        status_type = (event.get('status') or {}).get('type')
        hs = (event.get('homeScore') or {}).get('current') or 0
        as_ = (event.get('awayScore') or {}).get('current') or 0

        if status_type == 'inprogress':
            desc = (event.get('status') or {}).get('description') or ''
            minute = _live_minute(event)
            tag = f"{minute}'" if minute is not None else desc
            return f'{home_full} {hs}x{as_} {away_full}  ({tag})'
        if status_type == 'finished':
            return f'{home_full} {hs}x{as_} {away_full}  (FT)'
        start = event.get('startTimestamp')
        when = _format_when(start) if start else '?'
        return f'{home_full} x {away_full}  ({when})'
