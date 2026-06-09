"""Frontend Windows: mini-janela flutuante always-on-top (tkinter).

Como o Windows 11 não permite injetar texto fixo na barra de tarefas (Deskbands
foram removidos), este frontend é uma pílula discreta que fica sempre por cima,
mostrando um item por vez e rotacionando a cada poucos segundos — o mais próximo
de "fixo igual ao relógio".

- arrastável com o botão esquerdo (posição salva em config.json);
- botão direito abre o menu (atualizar / configurar / sair);
- não depende de GTK nem da bandeja.
"""

import os
import subprocess
import sys
import tkinter as tk

from PIL import Image, ImageTk

import widget_settings
from widget_core import WidgetCore

ICON_PNG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'claude-icon.png'
)
ICON_ICO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'claude-icon.ico'
)

ROTATION_TICKS = 10          # troca de item a cada 10 polls de 1s
POLL_MS = 1000               # re-render a cada 1s (pega dado novo / refresh)
ICON_SIZE = 18
MARGIN = 24                  # distância das bordas no posicionamento default
PIN_SEPARATOR = ' · '        # separa o rotativo (esquerda) dos fixos (direita)

BG = '#1e1e1e'
FG = '#f0f0f0'
FONT = ('Segoe UI', 10)


def _open_config_file():
    path = widget_settings.CONFIG_PATH
    if not os.path.exists(path):
        widget_settings.save(widget_settings.load())
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception:
        pass


class FloatWindow:
    def __init__(self, core: WidgetCore):
        self.core = core
        self._rotation_index = 0
        self._tick = 0
        self._icon_cache: dict[str, ImageTk.PhotoImage] = {}
        self._drag_offset = (0, 0)
        # âncora do canto direito: a janela cresce/encolhe pra ESQUERDA quando
        # o texto muda, pra nunca vazar pra fora da borda direita da tela.
        self._right = 0
        self._top = 0
        self._dragging = False
        # quando encaixada na barra (sem posição manual salva), guardamos a
        # faixa vertical da barra pra recentralizar o Y a cada ciclo — a altura
        # final da janela só é conhecida depois do primeiro render.
        self._docked = False
        self._dock_band: tuple[int, int] | None = None

        self.root = tk.Tk()
        self.root.overrideredirect(True)          # sem barra de título/borda
        self.root.attributes('-topmost', True)    # sempre por cima
        self.root.configure(bg=BG)
        try:
            # fundo transparente (Windows): a cor BG vira 100% transparente —
            # sobram só texto e ícones flutuando sobre a barra. As áreas
            # transparentes ficam click-through, mas texto/ícones continuam
            # arrastáveis e abrindo o menu normalmente.
            self.root.attributes('-transparentcolor', BG)
        except tk.TclError:
            # plataformas sem suporte (ex.: macOS) — cai num fundo translúcido
            self.root.attributes('-alpha', 0.93)

        # pílula = [ícone esq.] [texto rot.] [ícone dir.] [tail] [ícone fixo] [texto fixo]
        # empacotados lado a lado; o frame dá a margem externa.
        self.container = tk.Frame(self.root, bg=BG)
        self.container.pack(padx=10, pady=4)

        self.icon_left = tk.Label(self.container, bg=BG)
        self.text_rot = tk.Label(self.container, text='carregando…', bg=BG, fg=FG, font=FONT)
        self.icon_right = tk.Label(self.container, bg=BG)
        self.text_tail = tk.Label(self.container, bg=BG, fg=FG, font=FONT)
        self.icon_pinned = tk.Label(self.container, bg=BG)
        self.text_pinned = tk.Label(self.container, bg=BG, fg=FG, font=FONT)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label='Atualizar agora', command=self._on_refresh)
        self.menu.add_command(label='Configurar (abrir JSON)…', command=_open_config_file)
        self.menu.add_separator()
        self.menu.add_command(label='Sair', command=self._on_quit)

        drag_targets = (
            self.root, self.container, self.icon_left, self.text_rot,
            self.icon_right, self.text_tail, self.icon_pinned, self.text_pinned,
        )
        for widget in drag_targets:
            widget.bind('<Button-1>', self._on_drag_start)
            widget.bind('<B1-Motion>', self._on_drag_move)
            widget.bind('<ButtonRelease-1>', self._on_drag_end)
            widget.bind('<Button-3>', self._on_right_click)

        self._place_initial()

    # ---------- ícones ----------

    def _app_icon(self) -> ImageTk.PhotoImage:
        return self._load_icon('__app__')

    def _load_icon(self, path: str) -> ImageTk.PhotoImage:
        if path in self._icon_cache:
            return self._icon_cache[path]
        src = path
        if path == '__app__' or not os.path.isfile(path):
            src = ICON_PNG if os.path.exists(ICON_PNG) else ICON_ICO
        try:
            img = Image.open(src).convert('RGBA')
            # escala pela ALTURA preservando a proporção: ícones quadrados
            # (Claude, escudo único) viram 18x18; o escudo duplo de um jogo
            # vira uma faixa larga em vez de ficar espremido.
            w, h = img.size
            if h != ICON_SIZE:
                new_w = max(1, round(w * ICON_SIZE / h))
                img = img.resize((new_w, ICON_SIZE), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
        except Exception:
            photo = None
        self._icon_cache[path] = photo
        return photo

    # ---------- posicionamento ----------

    def _taskbar_dock(self, win_w: int, win_h: int):
        """Posição encaixada na barra de tarefas, centralizada verticalmente
        nela e logo à esquerda da área da bandeja (a setinha `^` + relógio).

        Usa Win32 pra achar a barra (Shell_TrayWnd) e a bandeja (TrayNotifyWnd).
        Retorna (x, y) ou None se não for Windows / não der pra detectar.
        """
        if not sys.platform.startswith('win'):
            return None
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            u.FindWindowW.restype = wintypes.HWND
            u.FindWindowExW.restype = wintypes.HWND
            u.FindWindowExW.argtypes = [
                wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
            ]
            u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

            tray = u.FindWindowW('Shell_TrayWnd', None)
            if not tray:
                return None
            trect = wintypes.RECT()
            u.GetWindowRect(tray, ctypes.byref(trect))

            notify = u.FindWindowExW(tray, None, 'TrayNotifyWnd', None)
            if notify:
                nrect = wintypes.RECT()
                u.GetWindowRect(notify, ctypes.byref(nrect))
                right = nrect.left - 8  # 8px de respiro antes da bandeja
            else:
                right = trect.right - 220  # fallback: estima largura da bandeja

            x = right - win_w
            # centraliza verticalmente dentro da faixa da barra
            y = trect.top + ((trect.bottom - trect.top) - win_h) // 2
            self._right = int(right)
            self._dock_band = (int(trect.top), int(trect.bottom))
            return int(x), int(y)
        except Exception:
            return None

    def _place_initial(self):
        self.root.update_idletasks()
        win = (widget_settings.load().get('window') or {})
        x, y = win.get('x'), win.get('y')
        w = self.root.winfo_width()
        h = self.root.winfo_height()

        if x is not None and y is not None:
            # usuário já arrastou pra um lugar — respeita
            self.root.geometry(f'+{int(x)}+{int(y)}')
            self.root.update_idletasks()
            self._right = int(x) + self.root.winfo_width()
            self._top = int(y)
            return

        docked = self._taskbar_dock(w, h)
        if docked is not None:
            x, y = docked
            self._docked = True
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = sw - w - MARGIN
            y = sh - h - MARGIN - 40  # acima da taskbar
            self._right = x + w
        self.root.geometry(f'+{int(x)}+{int(y)}')
        self.root.update_idletasks()
        self._top = int(y)

    def _reposition(self):
        """Mantém o canto direito fixo; cresce/encolhe pra esquerda. Faz clamp
        pra janela não sumir pelas bordas da tela."""
        if self._dragging:
            return
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # encaixada: recentraliza o Y na faixa da barra usando a altura ATUAL
        # (só conhecida após o render), senão fica baixa demais.
        if self._docked and self._dock_band:
            top, bottom = self._dock_band
            self._top = top + ((bottom - top) - h) // 2
        x = max(0, min(self._right - w, sw - w))
        y = max(0, min(self._top, sh - h))
        self.root.geometry(f'+{int(x)}+{int(y)}')
        # fica sobre a barra de tarefas (também topmost) — reforça o stacking
        # sem roubar foco, pra não ser coberta pela barra
        self.root.lift()

    def _save_position(self):
        self.root.update_idletasks()
        self._right = self.root.winfo_x() + self.root.winfo_width()
        self._top = self.root.winfo_y()
        cfg = widget_settings.load()
        cfg['window'] = {'x': self.root.winfo_x(), 'y': self.root.winfo_y()}
        widget_settings.save(cfg)

    # ---------- arrastar ----------

    def _on_drag_start(self, event):
        self._dragging = True
        self._drag_offset = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())

    def _on_drag_move(self, event):
        dx, dy = self._drag_offset
        self.root.geometry(f'+{event.x_root - dx}+{event.y_root - dy}')

    def _on_drag_end(self, _event):
        self._dragging = False
        self._save_position()

    def _on_right_click(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    # ---------- ações ----------

    def _on_refresh(self):
        self.core.refresh_now()
        self.root.after(300, self._render)

    def _on_quit(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # ---------- render / loop ----------

    def _render(self):
        # Fixos (config `pinned`) ficam sempre visíveis à direita; só os
        # rotativos giram, um por vez. Num jogo, o escudo da casa fica à esq. e
        # o do visitante grudado no nome dele: `🛡️ Casa 1x0 Fora 🛡️ 67' · Copa`.
        pinned, rotating = self.core.split_items()
        if not pinned and not rotating:
            self._layout(self._app_icon(), 'Claude — idle', None, '', None, '')
            self._reposition()
            return

        core_text = ''
        tail_text = ''
        left_icon = self._app_icon()
        right_icon = None
        if rotating:
            if self._rotation_index >= len(rotating):
                self._rotation_index = 0
            _, item_r = rotating[self._rotation_index]
            # item com escudo duplo parte o texto em core (antes do 2º escudo)
            # e tail (depois); senão é só o label inteiro no slot principal.
            if item_r.label_core is not None and item_r.icon_right_path:
                core_text = item_r.label_core
                tail_text = item_r.label_tail or ''
                right_icon = self._load_icon(item_r.icon_right_path)
            else:
                core_text = item_r.label
            if item_r.icon_path:
                ic = self._load_icon(item_r.icon_path)
                if ic is not None:
                    left_icon = ic

        pinned_text = PIN_SEPARATOR.join(item.label for _, item in pinned)
        has_rot = bool(core_text or tail_text)
        pinned_icon = None
        if has_rot and pinned:
            # mostra o ícone do Claude junto do texto fixo, mesmo com o jogo
            # girando à esquerda. Serve de separador (dispensa o ` · `).
            first_item = pinned[0][1]
            pinned_icon = (self._load_icon(first_item.icon_path)
                           if first_item.icon_path else None) or self._app_icon()
        elif not has_rot:
            # só fixos (sem nada rotacionando): texto fixo no slot principal,
            # com o ícone do Claude já à esquerda; sem escudo de visitante.
            core_text, pinned_text, right_icon = pinned_text, '', None

        self._layout(left_icon, core_text, right_icon, tail_text, pinned_icon, pinned_text)
        self._reposition()

    def _layout(self, left_icon, core_text, right_icon, tail_text, pinned_icon, pinned_text):
        """(Re)empacota os slots da pílula na ordem esq.→dir., escondendo os
        vazios. Chamado a cada poll, então é barato e idempotente."""
        for w in (self.icon_left, self.text_rot, self.icon_right,
                  self.text_tail, self.icon_pinned, self.text_pinned):
            w.pack_forget()

        self.icon_left.configure(image=left_icon or '')
        self.icon_left.image = left_icon  # mantém referência viva (evita GC)
        self.icon_left.pack(side='left')

        self.text_rot.configure(text=core_text)
        self.text_rot.pack(side='left', padx=(6, 0))

        if right_icon is not None:
            self.icon_right.configure(image=right_icon)
            self.icon_right.image = right_icon
            self.icon_right.pack(side='left', padx=(4, 0))  # grudado no nome

        if tail_text:
            self.text_tail.configure(text=tail_text)
            self.text_tail.pack(side='left', padx=(6, 0))

        if pinned_icon is not None:
            self.icon_pinned.configure(image=pinned_icon)
            self.icon_pinned.image = pinned_icon
            self.icon_pinned.pack(side='left', padx=(10, 0))  # separa do jogo

        if pinned_text:
            self.text_pinned.configure(text=pinned_text)
            self.text_pinned.pack(side='left', padx=(4, 0) if pinned_icon is not None else 0)

    def _loop(self):
        self._tick += 1
        if self._tick >= ROTATION_TICKS:
            self._tick = 0
            _, rotating = self.core.split_items()
            if len(rotating) > 1:
                self._rotation_index = (self._rotation_index + 1) % len(rotating)
            else:
                self._rotation_index = 0
        self._render()
        self.root.after(POLL_MS, self._loop)

    def run(self):
        self.core.start()  # fetch loops em threads; UI lê core.results no poll
        self._render()
        self.root.after(POLL_MS, self._loop)
        self.root.mainloop()


def run(providers):
    FloatWindow(WidgetCore(providers)).run()
