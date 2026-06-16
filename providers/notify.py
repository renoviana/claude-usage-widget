"""Notificações nativas do sistema operacional.

Linux  → gi.repository.Notify (libnotify / D-Bus), fallback notify-send.
         Som via canberra-gtk-play (non-blocking).
Windows → win10toast, fallback plyer.
         Som via winsound.
"""

import subprocess
import sys

_APP_NAME = 'claude-widget'
_notify_initted = False


def notify(title: str, body: str, icon: str | None = None, sound: bool = False) -> None:
    try:
        if sys.platform == 'win32':
            _win(title, body, icon, sound)
        else:
            _linux(title, body, icon, sound)
    except Exception:
        pass


def _linux(title: str, body: str, icon: str | None, sound: bool) -> None:
    global _notify_initted
    try:
        import gi
        gi.require_version('Notify', '0.7')
        from gi.repository import Notify
        if not _notify_initted:
            Notify.init(_APP_NAME)
            _notify_initted = True
        n = Notify.Notification.new(title, body, icon or 'dialog-information')
        n.show()
    except Exception:
        # fallback: notify-send
        cmd = ['notify-send', f'--app-name={_APP_NAME}']
        if icon:
            cmd += [f'--icon={icon}']
        cmd += [title, body]
        subprocess.run(cmd, check=False, timeout=5)

    if sound:
        subprocess.Popen(
            ['canberra-gtk-play', '--id=bell'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def _win(title: str, body: str, icon: str | None, sound: bool) -> None:
    if sound:
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast(title, body, icon_path=icon, duration=5, threaded=True)
        return
    except ImportError:
        pass
    import plyer
    plyer.notification.notify(title=title, message=body, app_name=_APP_NAME, timeout=5)
