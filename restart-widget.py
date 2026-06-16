#!/usr/bin/env python3
"""Sincroniza o repo com o dir de instalação e reinicia o widget.

Linux : pkill + rsync + nohup python3
Windows: taskkill + robocopy + pythonw
"""
import os
import subprocess
import sys
import time

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

if sys.platform == 'win32':
    INSTALL_DIR = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'claude-widget')
    LOG_FILE = os.path.join(os.environ.get('TEMP', os.path.expanduser('~')), 'claude-widget.log')
else:
    INSTALL_DIR = os.path.expanduser('~/.local/share/claude-widget')
    LOG_FILE = '/tmp/claude-widget.log'

WIDGET_SCRIPT = os.path.join(INSTALL_DIR, 'claude_widget.py')

RSYNC_EXCLUDES = [
    '--exclude=.git/',
    '--exclude=.claude/',
    '--exclude=__pycache__/',
    '--exclude=*.pyc',
    '--exclude=restart-widget.py',
    '--exclude=restart-widget.sh',
]

ROBOCOPY_EXCLUDES_DIRS = ['.git', '.claude', '__pycache__']
ROBOCOPY_EXCLUDES_FILES = ['*.pyc', 'restart-widget.py', 'restart-widget.sh']


def kill_widget():
    if sys.platform == 'win32':
        subprocess.run(
            ['powershell', '-Command',
             "Get-WmiObject Win32_Process | "
             "Where-Object { $_.CommandLine -like '*claude_widget*' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True,
        )
    else:
        subprocess.run(['pkill', '-f', 'claude_widget.py'], capture_output=True)


def sync_files():
    if sys.platform == 'win32':
        subprocess.run(
            ['robocopy', REPO_DIR, INSTALL_DIR, '/MIR', '/NJH', '/NJS',
             '/XD'] + ROBOCOPY_EXCLUDES_DIRS +
            ['/XF'] + ROBOCOPY_EXCLUDES_FILES,
            capture_output=True,
        )
    else:
        subprocess.run(
            ['rsync', '-a', '--delete'] + RSYNC_EXCLUDES +
            [f'{REPO_DIR}/', f'{INSTALL_DIR}/'],
            capture_output=True,
        )


def _python_bin():
    if sys.platform == 'win32':
        return 'pythonw'
    # Prefere o python3 do sistema (tem gi/GTK instalado via apt).
    # sys.executable pode ser o python do venv do Claude Code, que não tem gi.
    for candidate in ('/usr/bin/python3', '/usr/local/bin/python3'):
        if os.path.isfile(candidate):
            return candidate
    return sys.executable


def start_widget():
    env = os.environ.copy()
    with open(LOG_FILE, 'w') as log:
        subprocess.Popen(
            [_python_bin(), WIDGET_SCRIPT],
            env=env, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )


kill_widget()
time.sleep(0.5)
sync_files()
start_widget()
