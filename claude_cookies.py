import sqlite3
import shutil
import sys
import tempfile
import os
import glob
import json

MANUAL_COOKIES_PATH = os.path.expanduser('~/.config/claude-widget/cookies.json')


def _firefox_profile_patterns():
    home = os.path.expanduser('~')
    if sys.platform.startswith('win'):
        appdata = os.environ.get('APPDATA', '')
        return [os.path.join(appdata, 'Mozilla', 'Firefox', 'Profiles', '*', 'cookies.sqlite')]
    if sys.platform == 'darwin':
        return [os.path.join(home, 'Library', 'Application Support', 'Firefox', 'Profiles', '*', 'cookies.sqlite')]
    return [
        os.path.join(home, '.mozilla', 'firefox', '*', 'cookies.sqlite'),
        os.path.join(home, 'snap', 'firefox', 'common', '.mozilla', 'firefox', '*', 'cookies.sqlite'),
        os.path.join(home, '.var', 'app', 'org.mozilla.firefox', '.mozilla', 'firefox', '*', 'cookies.sqlite'),
    ]


def _find_firefox_profile():
    matches = []
    for pattern in _firefox_profile_patterns():
        matches.extend(glob.glob(pattern))
    if not matches:
        return None
    for path in matches:
        if 'default-release' in path:
            return path
    for path in matches:
        if 'default' in path:
            return path
    return matches[0]


def _read_firefox_cookies():
    db_path = _find_firefox_profile()
    if not db_path:
        return None

    tmp = tempfile.mktemp(suffix='.sqlite')
    shutil.copy2(db_path, tmp)
    try:
        conn = sqlite3.connect(tmp)
        rows = conn.execute(
            "SELECT name, value FROM moz_cookies WHERE host LIKE '%claude.ai%'",
        ).fetchall()
        conn.close()
        return {name: value for name, value in rows}
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _read_manual_cookies():
    if not os.path.exists(MANUAL_COOKIES_PATH):
        return None
    with open(MANUAL_COOKIES_PATH) as f:
        return json.load(f)


def get_claude_cookies():
    """Lê cookies do claude.ai.

    Ordem de tentativa:
    1. Arquivo manual em ~/.config/claude-widget/cookies.json (para Chrome/outros)
    2. Perfil do Firefox (Linux/macOS/Windows; suporta instalação padrão, Snap e Flatpak)
    """
    cookies = _read_manual_cookies()
    if cookies and 'sessionKey' in cookies and 'lastActiveOrg' in cookies:
        return cookies

    cookies = _read_firefox_cookies()
    if cookies and 'sessionKey' in cookies and 'lastActiveOrg' in cookies:
        return cookies

    raise FileNotFoundError(
        f'Cookies do Claude não encontrados. '
        f'Faça login no Firefox em claude.ai ou crie {MANUAL_COOKIES_PATH} '
        f'com sessionKey, lastActiveOrg, cf_clearance e __cf_bm.'
    )
