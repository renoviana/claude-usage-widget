import json
import os

CONFIG_PATH = os.path.expanduser('~/.config/claude-widget/config.json')

DEFAULT_CONFIG = {
    'pinned': [],
    'claude': {
        'claude_dir': '~/.claude',
    },
    'football': {
        'teams': [],
        'live_matches': False,
    },
    'weather': {
        'name': '',
        'latitude': None,
        'longitude': None,
    },
    'moon': {
        'enabled': False,
    },
}


def _merge_defaults(loaded: dict) -> dict:
    out = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if not isinstance(loaded, dict):
        return out
    for k, v in loaded.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def load() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH) as f:
            return _merge_defaults(json.load(f))
    except Exception:
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save(config: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
