from datetime import datetime

from curl_cffi import requests

import widget_settings

from .base import BarItem, Provider, ProviderResult

# Defaults usados se a config ainda não tem 'weather' (compat)
OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'

# Mapeamento de WMO weather code → (descrição PT, icon name do tema GTK)
# https://open-meteo.com/en/docs#weathervariables
_WEATHER_MAP = {
    0:  ('céu limpo',                 'weather-clear'),
    1:  ('predominantemente limpo',   'weather-few-clouds'),
    2:  ('parcialmente nublado',      'weather-few-clouds'),
    3:  ('nublado',                   'weather-overcast'),
    45: ('nevoeiro',                  'weather-fog'),
    48: ('nevoeiro com geada',        'weather-fog'),
    51: ('garoa fraca',               'weather-showers-scattered'),
    53: ('garoa moderada',            'weather-showers-scattered'),
    55: ('garoa intensa',             'weather-showers-scattered'),
    56: ('garoa congelante fraca',    'weather-showers-scattered'),
    57: ('garoa congelante intensa',  'weather-showers-scattered'),
    61: ('chuva fraca',               'weather-showers'),
    63: ('chuva moderada',            'weather-showers'),
    65: ('chuva forte',               'weather-showers'),
    66: ('chuva congelante fraca',    'weather-showers'),
    67: ('chuva congelante forte',    'weather-showers'),
    71: ('neve fraca',                'weather-snow'),
    73: ('neve moderada',             'weather-snow'),
    75: ('neve forte',                'weather-snow'),
    77: ('granizo de neve',           'weather-snow'),
    80: ('pancadas fracas',           'weather-showers-scattered'),
    81: ('pancadas moderadas',        'weather-showers'),
    82: ('pancadas violentas',        'weather-showers'),
    85: ('pancadas de neve fracas',   'weather-snow'),
    86: ('pancadas de neve fortes',   'weather-snow'),
    95: ('trovoada',                  'weather-storm'),
    96: ('trovoada com granizo',      'weather-storm'),
    99: ('trovoada forte com granizo','weather-storm'),
}


def _describe(code) -> tuple[str, str]:
    return _WEATHER_MAP.get(code, ('—', 'weather-overcast'))


class WeatherProvider(Provider):
    name = 'weather'
    refresh_interval = 30 * 60  # 30 min

    def __init__(self):
        self._location_name = ''
        self._lat = None
        self._lon = None
        self._reload_config()

    def _reload_config(self):
        cfg = widget_settings.load().get('weather') or {}
        self._location_name = cfg.get('name') or ''
        self._lat = cfg.get('latitude')
        self._lon = cfg.get('longitude')

    def _is_configured(self) -> bool:
        return self._lat is not None and self._lon is not None

    def fetch(self) -> ProviderResult:
        self._reload_config()
        if not self._is_configured():
            return ProviderResult()
        try:
            r = requests.get(
                OPEN_METEO_URL,
                params={
                    'latitude': self._lat,
                    'longitude': self._lon,
                    'current': 'temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m',
                    'timezone': 'auto',
                },
                impersonate='firefox133',
                timeout=10,
            )
            r.raise_for_status()
            return ProviderResult(data=r.json())
        except Exception as exc:
            return ProviderResult(error=f'open-meteo: {exc}')

    def _current(self, result: ProviderResult) -> dict | None:
        if result.error or not result.data:
            return None
        return result.data.get('current')

    def items(self, result: ProviderResult) -> list[BarItem]:
        if not self._is_configured():
            return []
        cur = self._current(result)
        if not cur:
            return []
        temp = cur.get('temperature_2m')
        if temp is None:
            return []
        _, icon = _describe(cur.get('weather_code'))
        return [BarItem(
            label=f'{round(temp)}°C',
            icon_path=icon,
            pin_id=self.name,
        )]

    def menu_header(self, result: ProviderResult) -> str | None:
        if not self._is_configured():
            return None
        if result.error:
            return 'Clima · erro'
        cur = self._current(result)
        if not cur:
            return None
        temp = cur.get('temperature_2m')
        if temp is None:
            return None
        desc, _ = _describe(cur.get('weather_code'))
        return f'Clima · {round(temp)}°C · {desc}'

    def render_menu(self, result: ProviderResult) -> list:
        if result.error:
            return [f'erro: {result.error[:60]}']

        cur = self._current(result)
        if not cur:
            return []

        humidity = cur.get('relative_humidity_2m')
        wind = cur.get('wind_speed_10m')
        updated = cur.get('time') or ''

        out = []
        if self._location_name:
            out.append(self._location_name)
        if humidity is not None:
            out.append(f'umidade {humidity}%')
        if wind is not None:
            out.append(f'vento {wind} km/h')
        if updated:
            try:
                t = datetime.fromisoformat(updated)
                upd_str = t.strftime('%H:%M')
            except Exception:
                upd_str = updated
            out.append(f'atualizado {upd_str}')

        return out
