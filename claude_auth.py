import json
import os
import time

CREDENTIALS_PATH = os.path.expanduser('~/.claude/.credentials.json')


class TokenMissing(Exception):
    pass


class TokenExpired(Exception):
    pass


def get_oauth_token():
    """Retorna o accessToken do Claude Code em ~/.claude/.credentials.json.

    Levanta TokenMissing se o arquivo/campo não existir, e TokenExpired se
    `expiresAt` já passou. O refresh fica a cargo do CLI `claude`.
    """
    if not os.path.exists(CREDENTIALS_PATH):
        raise TokenMissing(f'{CREDENTIALS_PATH} não encontrado')

    with open(CREDENTIALS_PATH) as f:
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
