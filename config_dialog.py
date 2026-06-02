import threading

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from curl_cffi import requests

import widget_settings

SOFASCORE_BASE = 'https://api.sofascore.com/api/v1'
OPEN_METEO_GEOCODING = 'https://geocoding-api.open-meteo.com/v1/search'


class ConfigDialog(Gtk.Window):
    def __init__(self, on_save=None):
        super().__init__(title='Configurar widget')
        self.set_default_size(440, 600)
        self.set_border_width(12)
        self._on_save = on_save

        self._config = widget_settings.load()
        football_cfg = self._config.setdefault('football', {})
        self._teams: list[dict] = list(football_cfg.get('teams') or [])
        self._live_matches: bool = bool(football_cfg.get('live_matches'))
        self._pinned: list[str] = list(self._config.get('pinned') or [])

        weather_cfg = self._config.setdefault('weather', {})
        self._weather = {
            'name': weather_cfg.get('name') or '',
            'latitude': weather_cfg.get('latitude'),
            'longitude': weather_cfg.get('longitude'),
        }

        moon_cfg = self._config.setdefault('moon', {})
        self._moon_enabled: bool = bool(moon_cfg.get('enabled'))

        claude_cfg = self._config.setdefault('claude', {})
        self._claude_dir = claude_cfg.get('claude_dir') or '~/.claude'

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(outer)

        notebook = Gtk.Notebook()
        notebook.append_page(
            self._tab_wrap(self._build_claude_section()),
            Gtk.Label(label='Claude'),
        )
        notebook.append_page(
            self._tab_wrap(self._build_football_tab()),
            Gtk.Label(label='Futebol'),
        )
        notebook.append_page(
            self._tab_wrap(self._build_weather_section()),
            Gtk.Label(label='Clima'),
        )
        notebook.append_page(
            self._tab_wrap(self._build_moon_section()),
            Gtk.Label(label='Lua'),
        )
        notebook.append_page(
            self._tab_wrap(self._build_pin_section()),
            Gtk.Label(label='Fixar na barra'),
        )
        outer.pack_start(notebook, True, True, 0)
        outer.pack_start(self._build_actions(), False, False, 0)

    @staticmethod
    def _tab_wrap(widget: Gtk.Widget) -> Gtk.Widget:
        """Embrulha o conteúdo de uma aba com padding e (se preciso) scroll."""
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(10)
        box.pack_start(widget, True, True, 0)
        scroll.add(box)
        return scroll

    def _build_football_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(self._build_teams_section(), True, True, 0)
        box.pack_start(Gtk.Separator(), False, False, 4)
        box.pack_start(self._build_search_section(), False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 4)
        box.pack_start(self._build_live_toggle(), False, False, 0)
        return box

    # ---------- Times monitorados ----------

    def _build_teams_section(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label = Gtk.Label(label='Times monitorados', xalign=0)
        label.get_style_context().add_class('heading')
        box.pack_start(label, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(120)
        self._teams_list = Gtk.ListBox()
        self._teams_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled.add(self._teams_list)
        box.pack_start(scrolled, True, True, 0)

        self._refresh_teams_list()
        return box

    def _refresh_teams_list(self):
        for child in self._teams_list.get_children():
            self._teams_list.remove(child)
        if not self._teams:
            row = Gtk.ListBoxRow()
            row.add(Gtk.Label(label='(nenhum time — use a busca abaixo)', xalign=0))
            self._teams_list.add(row)
        for team in self._teams:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            label = Gtk.Label(label=f"{team['name']}  ·  id {team['id']}", xalign=0)
            hbox.pack_start(label, True, True, 0)
            remove_btn = Gtk.Button(label='remover')
            remove_btn.connect('clicked', self._on_remove_team, team['id'])
            hbox.pack_end(remove_btn, False, False, 0)
            row.add(hbox)
            self._teams_list.add(row)
        self._teams_list.show_all()

    def _on_remove_team(self, _btn, team_id):
        self._teams = [t for t in self._teams if t.get('id') != team_id]
        # remove pin desse time se estava marcado
        pin_id = f'football:team:{team_id}'
        self._pinned = [p for p in self._pinned if p != pin_id]
        self._refresh_teams_list()
        self._refresh_pin_section()

    # ---------- Claude ----------

    def _build_claude_section(self) -> Gtk.Widget:
        import os
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(
            Gtk.Label(label='Caminho do diretório .claude', xalign=0),
            False, False, 0,
        )

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._claude_entry = Gtk.Entry()
        self._claude_entry.set_text(self._claude_dir)
        row.pack_start(self._claude_entry, True, True, 0)
        browse = Gtk.Button(label='Procurar…')
        browse.connect('clicked', self._on_claude_browse)
        row.pack_end(browse, False, False, 0)
        box.pack_start(row, False, False, 0)

        self._claude_status = Gtk.Label(xalign=0)
        self._claude_status.set_markup('')
        self._refresh_claude_status()
        box.pack_start(self._claude_status, False, False, 0)

        # atualiza status enquanto o user digita
        self._claude_entry.connect(
            'changed',
            lambda _e: self._refresh_claude_status(),
        )
        return box

    def _refresh_claude_status(self):
        import os
        path = os.path.expanduser(
            os.path.join(self._claude_entry.get_text() or '~/.claude', '.credentials.json')
        )
        if os.path.exists(path):
            self._claude_status.set_markup(
                f'<small>✓ .credentials.json encontrado em {path}</small>'
            )
        else:
            self._claude_status.set_markup(
                f'<small>✗ .credentials.json NÃO encontrado em {path} '
                f'— widget Claude ficará oculto até existir</small>'
            )

    def _on_claude_browse(self, _btn):
        import os
        dialog = Gtk.FileChooserDialog(
            title='Selecionar diretório .claude',
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            'Cancelar', Gtk.ResponseType.CANCEL,
            'Selecionar', Gtk.ResponseType.OK,
        )
        try:
            current = os.path.expanduser(self._claude_entry.get_text() or '~')
            if os.path.isdir(current):
                dialog.set_current_folder(current)
        except Exception:
            pass

        if dialog.run() == Gtk.ResponseType.OK:
            chosen = dialog.get_filename()
            home = os.path.expanduser('~')
            # Guarda como path com ~ quando dentro do home, pra ser portável.
            if chosen.startswith(home + '/'):
                chosen = '~' + chosen[len(home):]
            self._claude_entry.set_text(chosen)
        dialog.destroy()
        self._refresh_claude_status()

    # ---------- Clima ----------

    def _build_weather_section(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label = Gtk.Label(label='Cidade do clima', xalign=0)
        box.pack_start(label, False, False, 0)

        self._weather_current = Gtk.Label(xalign=0)
        self._refresh_weather_current_label()
        box.pack_start(self._weather_current, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._city_entry = Gtk.Entry()
        self._city_entry.set_placeholder_text('Buscar cidade…')
        self._city_entry.connect('activate', self._on_city_search)
        row.pack_start(self._city_entry, True, True, 0)
        self._city_btn = Gtk.Button(label='Buscar')
        self._city_btn.connect('clicked', self._on_city_search)
        row.pack_end(self._city_btn, False, False, 0)
        box.pack_start(row, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(100)
        self._city_results = Gtk.ListBox()
        self._city_results.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled.add(self._city_results)
        box.pack_start(scrolled, False, False, 0)
        return box

    def _refresh_weather_current_label(self):
        name = self._weather.get('name') or ''
        lat = self._weather.get('latitude')
        lon = self._weather.get('longitude')
        if name and lat is not None and lon is not None:
            self._weather_current.set_text(
                f'Atual: {name} ({lat:.2f}, {lon:.2f})'
            )
        else:
            self._weather_current.set_text(
                'Nenhuma cidade configurada — widget de clima fica oculto'
            )

    def _on_city_search(self, *_args):
        query = (self._city_entry.get_text() or '').strip()
        if not query:
            return
        self._city_btn.set_sensitive(False)
        self._set_city_results_message('buscando…')
        threading.Thread(
            target=self._do_city_search, args=(query,), daemon=True,
        ).start()

    def _do_city_search(self, query: str):
        try:
            r = requests.get(
                OPEN_METEO_GEOCODING,
                params={
                    'name': query,
                    'count': 10,
                    'language': 'pt',
                },
                impersonate='firefox133',
                timeout=10,
            )
            r.raise_for_status()
            results = r.json().get('results') or []
        except Exception as exc:
            GLib.idle_add(self._on_city_search_error, str(exc))
            return
        GLib.idle_add(self._on_city_search_results, results)

    def _on_city_search_error(self, msg: str):
        self._city_btn.set_sensitive(True)
        self._set_city_results_message(f'erro: {msg[:60]}')
        return False

    def _on_city_search_results(self, results: list[dict]):
        self._city_btn.set_sensitive(True)
        for child in self._city_results.get_children():
            self._city_results.remove(child)
        if not results:
            self._set_city_results_message('nenhuma cidade encontrada')
            return False
        for city in results:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            parts = [city.get('name') or '?']
            if city.get('admin1'):
                parts.append(city['admin1'])
            if city.get('country'):
                parts.append(city['country'])
            text = ' · '.join(parts)
            hbox.pack_start(Gtk.Label(label=text, xalign=0), True, True, 0)
            pick = Gtk.Button(label='usar')
            pick.connect('clicked', self._on_city_pick, city)
            hbox.pack_end(pick, False, False, 0)
            row.add(hbox)
            self._city_results.add(row)
        self._city_results.show_all()
        return False

    def _set_city_results_message(self, msg: str):
        for child in self._city_results.get_children():
            self._city_results.remove(child)
        row = Gtk.ListBoxRow()
        row.add(Gtk.Label(label=msg, xalign=0))
        self._city_results.add(row)
        self._city_results.show_all()

    def _on_city_pick(self, _btn, city):
        self._weather = {
            'name': city.get('name') or '?',
            'latitude': float(city.get('latitude') or 0),
            'longitude': float(city.get('longitude') or 0),
        }
        self._refresh_weather_current_label()
        self._set_city_results_message(f'definido: {self._weather["name"]}')

    # ---------- Lua ----------

    def _build_moon_section(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.pack_start(
            Gtk.Label(
                label='Mostrar próxima lua cheia (só quando faltar < 7 dias)',
                xalign=0,
            ),
            True, True, 0,
        )
        self._moon_switch = Gtk.Switch()
        self._moon_switch.set_active(self._moon_enabled)
        row.pack_end(self._moon_switch, False, False, 0)
        box.pack_start(row, False, False, 0)
        return box

    # ---------- Pinagem ----------

    def _pinnable_items(self) -> list[tuple[str, str]]:
        """(pin_id, label legível) — todos os items fixáveis disponíveis."""
        out = [
            ('claude', 'Consumo Claude'),
            ('weather', 'Clima'),
            ('moon', 'Lua cheia (quando próxima)'),
        ]
        for team in self._teams:
            out.append((f"football:team:{team['id']}", f"Time · {team['name']}"))
        return out

    def _build_pin_section(self) -> Gtk.Widget:
        self._pin_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._pin_box.pack_start(
            Gtk.Label(
                label='Fixados na barra (ordem: esquerda → direita)',
                xalign=0,
            ),
            False, False, 0,
        )
        self._pinned_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._pin_box.pack_start(self._pinned_list_box, False, False, 0)

        self._pin_box.pack_start(Gtk.Separator(), False, False, 4)
        self._pin_box.pack_start(
            Gtk.Label(label='Disponíveis pra fixar', xalign=0),
            False, False, 0,
        )
        self._available_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._pin_box.pack_start(self._available_list_box, False, False, 0)

        self._refresh_pin_section()
        return self._pin_box

    def _refresh_pin_section(self):
        for child in self._pinned_list_box.get_children():
            self._pinned_list_box.remove(child)
        for child in self._available_list_box.get_children():
            self._available_list_box.remove(child)

        pinnable = self._pinnable_items()
        labels = dict(pinnable)

        # Mantém só pin_ids ainda válidos (ex.: time removido sai)
        self._pinned = [pid for pid in self._pinned if pid in labels]

        if not self._pinned:
            empty = Gtk.Label(label='(nenhum — use a lista abaixo)', xalign=0)
            empty.get_style_context().add_class('dim-label')
            self._pinned_list_box.pack_start(empty, False, False, 0)
        for idx, pid in enumerate(self._pinned):
            self._pinned_list_box.pack_start(
                self._pin_row_pinned(pid, labels[pid], idx, len(self._pinned)),
                False, False, 0,
            )

        available = [(pid, lbl) for pid, lbl in pinnable if pid not in self._pinned]
        if not available:
            empty = Gtk.Label(label='(tudo já fixado)', xalign=0)
            empty.get_style_context().add_class('dim-label')
            self._available_list_box.pack_start(empty, False, False, 0)
        for pid, lbl in available:
            self._available_list_box.pack_start(
                self._pin_row_available(pid, lbl),
                False, False, 0,
            )

        self._pin_box.show_all()

    def _pin_row_pinned(self, pid: str, label: str, idx: int, total: int) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
        up = Gtk.Button(label='↑')
        up.set_sensitive(idx > 0)
        up.connect('clicked', self._on_pin_move, pid, -1)
        row.pack_end(up, False, False, 0)
        down = Gtk.Button(label='↓')
        down.set_sensitive(idx < total - 1)
        down.connect('clicked', self._on_pin_move, pid, +1)
        row.pack_end(down, False, False, 0)
        unpin = Gtk.Button(label='✗')
        unpin.connect('clicked', self._on_pin_remove, pid)
        row.pack_end(unpin, False, False, 0)
        return row

    def _pin_row_available(self, pid: str, label: str) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
        add = Gtk.Button(label='+')
        add.connect('clicked', self._on_pin_add, pid)
        row.pack_end(add, False, False, 0)
        return row

    def _on_pin_move(self, _btn, pid: str, delta: int):
        try:
            i = self._pinned.index(pid)
        except ValueError:
            return
        j = i + delta
        if 0 <= j < len(self._pinned):
            self._pinned[i], self._pinned[j] = self._pinned[j], self._pinned[i]
        self._refresh_pin_section()

    def _on_pin_remove(self, _btn, pid: str):
        self._pinned = [p for p in self._pinned if p != pid]
        self._refresh_pin_section()

    def _on_pin_add(self, _btn, pid: str):
        if pid not in self._pinned:
            self._pinned.append(pid)
        self._refresh_pin_section()

    # ---------- Busca ----------

    def _build_search_section(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label = Gtk.Label(label='Adicionar time (busca no Sofascore)', xalign=0)
        box.pack_start(label, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._search_entry = Gtk.Entry()
        self._search_entry.set_placeholder_text('Nome do time')
        self._search_entry.connect('activate', self._on_search)
        row.pack_start(self._search_entry, True, True, 0)
        self._search_btn = Gtk.Button(label='Buscar')
        self._search_btn.connect('clicked', self._on_search)
        row.pack_end(self._search_btn, False, False, 0)
        box.pack_start(row, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(120)
        self._results_list = Gtk.ListBox()
        self._results_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled.add(self._results_list)
        box.pack_start(scrolled, True, True, 0)
        return box

    def _on_search(self, *_args):
        query = (self._search_entry.get_text() or '').strip()
        if not query:
            return
        self._search_btn.set_sensitive(False)
        self._set_results_message('buscando…')
        threading.Thread(
            target=self._do_search, args=(query,), daemon=True,
        ).start()

    def _do_search(self, query: str):
        try:
            r = requests.get(
                f'{SOFASCORE_BASE}/search/all',
                params={'q': query, 'page': 0},
                impersonate='firefox133',
                timeout=10,
            )
            r.raise_for_status()
            results = r.json().get('results') or []
        except Exception as exc:
            GLib.idle_add(self._on_search_error, str(exc))
            return
        teams = []
        for item in results:
            if item.get('type') != 'team':
                continue
            entity = item.get('entity') or {}
            sport = ((entity.get('sport') or {}).get('name') or '').lower()
            if sport != 'football':
                continue
            teams.append(entity)
            if len(teams) >= 12:
                break
        GLib.idle_add(self._on_search_results, teams)

    def _on_search_error(self, msg: str):
        self._search_btn.set_sensitive(True)
        self._set_results_message(f'erro: {msg[:60]}')
        return False

    def _on_search_results(self, teams: list[dict]):
        self._search_btn.set_sensitive(True)
        for child in self._results_list.get_children():
            self._results_list.remove(child)
        if not teams:
            self._set_results_message('nenhum time encontrado')
            return False
        existing_ids = {t.get('id') for t in self._teams}
        for entity in teams:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            country = ((entity.get('country') or {}).get('name')) or ''
            text = entity.get('name') or '?'
            if country:
                text = f'{text}  ·  {country}'
            hbox.pack_start(Gtk.Label(label=text, xalign=0), True, True, 0)
            if entity.get('id') in existing_ids:
                hbox.pack_end(Gtk.Label(label='(já adicionado)', xalign=1), False, False, 0)
            else:
                add_btn = Gtk.Button(label='+')
                add_btn.connect('clicked', self._on_add_team, entity)
                hbox.pack_end(add_btn, False, False, 0)
            row.add(hbox)
            self._results_list.add(row)
        self._results_list.show_all()
        return False

    def _set_results_message(self, msg: str):
        for child in self._results_list.get_children():
            self._results_list.remove(child)
        row = Gtk.ListBoxRow()
        row.add(Gtk.Label(label=msg, xalign=0))
        self._results_list.add(row)
        self._results_list.show_all()

    def _on_add_team(self, _btn, entity):
        team_id = entity.get('id')
        if any(t.get('id') == team_id for t in self._teams):
            return
        self._teams.append({'id': team_id, 'name': entity.get('name') or '?'})
        self._refresh_teams_list()
        self._refresh_pin_section()
        # re-renderiza resultados pra esconder o botão "+"
        self._on_search_results([])

    # ---------- Toggle ao vivo ----------

    def _build_live_toggle(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(
            label='Acompanhar todos os jogos ao vivo (substitui os times)',
            xalign=0,
        )
        row.pack_start(label, True, True, 0)
        self._live_switch = Gtk.Switch()
        self._live_switch.set_active(self._live_matches)
        row.pack_end(self._live_switch, False, False, 0)
        return row

    # ---------- Ações ----------

    def _build_actions(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cancel = Gtk.Button(label='Cancelar')
        cancel.connect('clicked', lambda _b: self.destroy())
        row.pack_end(cancel, False, False, 0)
        save = Gtk.Button(label='Salvar')
        save.connect('clicked', self._on_save_clicked)
        row.pack_end(save, False, False, 0)
        return row

    def _on_save_clicked(self, _btn):
        self._config.setdefault('football', {})
        self._config['football']['teams'] = self._teams
        self._config['football']['live_matches'] = self._live_switch.get_active()
        self._config['weather'] = self._weather
        self._config['moon'] = {'enabled': self._moon_switch.get_active()}
        self._config['pinned'] = list(self._pinned)  # preserva ordem do usuário
        self._config.setdefault('claude', {})
        self._config['claude']['claude_dir'] = (
            self._claude_entry.get_text() or '~/.claude'
        )
        widget_settings.save(self._config)
        if self._on_save:
            try:
                self._on_save()
            except Exception:
                pass
        self.destroy()
