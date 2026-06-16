from dataclasses import dataclass, field
from typing import Any

# Sentinela usada nas listas de `render_menu`: um item `None` vira um separador
# no frontend (Gtk.SeparatorMenuItem / pystray.Menu.SEPARATOR).
MENU_SEPARATOR = None


@dataclass
class ProviderResult:
    """Resultado de um ciclo de fetch.

    - `data`: payload livre, repassado pra render_bar/render_menu.
    - `error`: mensagem curta se o fetch falhou; data pode vir None nesse caso.
    """
    data: Any = None
    error: str | None = None
    notifications: list = field(default_factory=list)  # [(title, body, icon_path|None)]


@dataclass
class BarItem:
    """Um slot da rotação na barra do topo.

    Cada provider pode contribuir com N items (ex.: vários times monitorados,
    ou vários jogos ao vivo). O indicador concatena todos os items de todos
    os providers e rotaciona linearmente entre eles.

    `pin_id` identifica o item pra fins de fixação na barra (config `pinned`).
    `None` significa que o item não é fixável (ex.: jogos do feed ao vivo).

    `icon_right_path` é um ícone OPCIONAL exibido à direita do texto (ex.: escudo
    do visitante num jogo). Frontends que só suportam um ícone (AppIndicator do
    GTK) ignoram esse campo e usam apenas `label` + `icon_path`.

    Pra flanquear o escudo do visitante exatamente após o nome dele, o item pode
    partir o texto em `label_core` (antes do escudo da direita) e `label_tail`
    (depois): `🛡️ {label_core} 🛡️ {label_tail}`. Quando ausentes, frontends com
    dois ícones caem no `label` inteiro. `label` continua sendo o texto COMPLETO
    (core + tail) — é o que GTK/bandeja consomem, então nada muda pra eles.
    """
    label: str
    icon_path: str | None = None
    pin_id: str | None = None
    icon_right_path: str | None = None
    label_core: str | None = None
    label_tail: str | None = None


class Provider:
    """Fonte de informação plugável do widget.

    Cada provider roda em sua própria cadência (`refresh_interval`) e
    contribui com zero, um ou mais `BarItem`s pra rotação da barra,
    além de items pro menu.
    """

    name: str = ''
    refresh_interval: int = 300  # segundos

    def fetch(self) -> ProviderResult:
        """Busca dados; chamado em thread daemon. Não tocar GTK aqui."""
        raise NotImplementedError

    def next_refresh_seconds(self) -> int:
        """Segundos até o próximo fetch. Default usa refresh_interval fixo.

        Override pra cadência dinâmica (ex.: poll rápido durante jogo ao vivo,
        lento quando não há nada acontecendo).
        """
        return self.refresh_interval

    def menu_header(self, result: ProviderResult) -> str | None:
        """Texto curto do provider na linha top-level do menu.

        Retornar `None` faz o provider não aparecer no menu (idle).
        """
        return None

    def render_menu(self, result: ProviderResult) -> list:
        """Linhas de texto que vão pro SUBMENU desse provider.

        Retorna uma lista de `str` (linhas informativas, não-clicáveis) onde
        um item `MENU_SEPARATOR` (None) representa um separador. Mantém os
        providers agnósticos de toolkit — o frontend (GTK/tray) traduz cada
        linha pro widget nativo. Lista vazia = item top-level sem submenu.
        """
        return []

    def items(self, result: ProviderResult) -> list[BarItem]:
        """Items que entram na rotação da barra. Default: um único item
        derivado de `render_bar()` + `icon_path()`, com pin_id = nome do
        provider. Retornar lista vazia significa "estou idle, me tire da
        rotação".
        """
        label = self.render_bar(result)
        if label is None:
            return []
        return [BarItem(
            label=label,
            icon_path=self.icon_path(result),
            pin_id=self.name,
        )]

    # API legada — providers single-item podem só implementar essas duas
    # em vez de override do items().

    def render_bar(self, result: ProviderResult) -> str | None:
        return None

    def icon_path(self, result: ProviderResult) -> str | None:
        return None
