"""Entry point do widget — escolhe o frontend conforme a plataforma.

- Linux  → AppIndicator GTK na barra do topo (frontends/gtk_indicator.py)
- Windows/macOS → ícone na bandeja via pystray (frontends/tray.py)

Os providers e a lógica (widget_core.py) são compartilhados entre os dois.
"""

import sys

import widget_settings
from providers import (
    ClaudeUsageProvider, FootballProvider, MoonProvider, WeatherProvider,
)


def build_providers():
    return [
        ClaudeUsageProvider(),
        FootballProvider(),
        MoonProvider(),
        WeatherProvider(),
    ]


def main():
    providers = build_providers()
    if sys.platform.startswith('linux'):
        from frontends.gtk_indicator import run
    elif (widget_settings.load().get('frontend') or 'float') == 'tray':
        from frontends.tray import run
    else:
        from frontends.float_window import run
    run(providers)


if __name__ == '__main__':
    main()
