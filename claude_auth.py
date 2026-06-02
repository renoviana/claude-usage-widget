import json
import os
import time

import widget_settings

DEFAULT_CLAUDE_DIR = '~/.claude'


class TokenMissing(Exception):
    pass


class TokenExpired(Exception):
    pass


def get_credentials_path() -> str:
    """Resolve o caminho de .credentials.json baseado no config."""
    cfg = widget_settings.load().get('claude') or {}
    base = cfg.get('claude_dir') or DEFAULT_CLAUDE_DIR
    return os.path.join(os.path.expanduser(base), '.credentials.json')


def get_oauth_token():
    """Retorna o accessToken do Claude Code do .credentials.json configurado.

    Levanta TokenMissing se o arquivo/campo não existir, e TokenExpired se
    `expiresAt` já passou. O refresh fica a cargo do CLI `claude`.
    """
    path = get_credentials_path()
    if not os.path.exists(path):
        raise TokenMissing(f'{path} não encontrado')

    with open(path) as f:
        data = json.load(f)

    oauth = data.get('claudeAiOauth') or {}
    token = oauth.get('accessToken')
    if not token:
        raise TokenMissing('claudeAiOauth.accessToken ausente')

    expires_at = oauth.get('expiresAt') or 0
    # expiresAt está em milissegundos
    if expires_at and expires_at / 1000 <= time.time():
        raise TokenExpired('accessToken expirado — rode `claude` para renovar')

    return token
