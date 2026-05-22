# Claude Widget

AppIndicator para a barra do topo do GNOME/Ubuntu que exibe o consumo do
[claude.ai](https://claude.ai) em tempo real (janela de 5h, 7d e créditos extras).

<img width="431" height="28" alt="image" src="https://github.com/user-attachments/assets/785d460b-b1c5-407d-8bd0-5dffbf752220" />


## Como funciona

O widget lê os cookies da sua sessão no navegador, chama a API privada
`/api/organizations/{org}/usage` (a mesma usada pela tela de `Settings → Usage`)
e atualiza a label do AppIndicator a cada 5 minutos. Valores em 0% são
omitidos da barra para reduzir ruído.

## Requisitos

- Linux com GNOME (Ubuntu, Fedora, Pop!_OS etc.)
- Python 3.10+
- Extensão "AppIndicator and KStatusNotifierItem Support" ativa no GNOME
  (já vem ativa por padrão no Ubuntu 22.04+)
- Conta no [claude.ai](https://claude.ai) logada no Firefox **ou** Chrome

## Instalação

```bash
git clone https://github.com/SEU-USUARIO/claude-widget.git ~/.local/share/claude-widget
cd ~/.local/share/claude-widget
./install.sh
```

O `install.sh` faz:
1. Verifica e instala `python3-gi`, `gir1.2-gtk-3.0` e
   `gir1.2-ayatanaappindicator3-0.1` via apt (pede sudo se necessário).
2. Instala `curl_cffi` e `Pillow` no Python do sistema (`pip install --user`).
3. Cria `~/.config/autostart/claude-widget.desktop` para iniciar no login.

Para rodar agora sem reiniciar a sessão:

```bash
/usr/bin/python3 ~/.local/share/claude-widget/claude_widget.py &
```

## Configurando os cookies

O widget precisa de cookies autenticados do `claude.ai`. Os cookies essenciais
são: `sessionKey`, `lastActiveOrg`, `cf_clearance` e `__cf_bm`.

### Firefox (automático)

Basta estar logado em `claude.ai` no Firefox. O widget lê os cookies direto
do perfil (`cookies.sqlite`), suportando instalações padrão, Snap e Flatpak.

Se o widget mostrar erro de Cloudflare, abra `claude.ai` no Firefox uma vez
para renovar o `cf_clearance` (cookie volátil, expira a cada ~2h).

### Chrome / outros navegadores (manual)

Crie o arquivo `~/.config/claude-widget/cookies.json` com os cookies copiados
do DevTools:

1. Abra `claude.ai` no Chrome.
2. Pressione `F12` → aba **Application** → **Cookies** → `https://claude.ai`.
3. Copie os valores de `sessionKey`, `lastActiveOrg`, `cf_clearance` e `__cf_bm`.
4. Crie o arquivo:

```bash
mkdir -p ~/.config/claude-widget
cat > ~/.config/claude-widget/cookies.json <<'EOF'
{
  "sessionKey": "sk-ant-sid01-...",
  "lastActiveOrg": "00000000-0000-0000-0000-000000000000",
  "cf_clearance": "...",
  "__cf_bm": "..."
}
EOF
```

> O `cf_clearance` expira a cada ~2h. Se o widget começar a falhar, volte ao
> Chrome, recarregue `claude.ai` e atualize o valor no JSON.

O widget tenta primeiro `cookies.json`; se não existir ou estiver incompleto,
cai no Firefox automaticamente.

## Por que `curl_cffi` em vez de `requests`?

A Anthropic protege a API com Cloudflare, que faz **fingerprint TLS (JA3)** —
ou seja, identifica que `requests` e `curl` padrão não são navegadores reais
e retorna `403 "Just a moment..."` mesmo com cookies válidos.

`curl_cffi` usa o binário do curl com a handshake TLS de um Firefox real
(`impersonate='firefox133'`), passando despercebido.

## Troubleshooting

| Sintoma | Causa provável | Solução |
| --- | --- | --- |
| Ícone não aparece na barra | Extensão AppIndicator desativada | `gnome-extensions enable ubuntu-appindicators@ubuntu.com` |
| `bloqueado pelo Cloudflare` | `cf_clearance` expirado | Abra `claude.ai` no navegador uma vez |
| `Cookies não encontrados` | Perfil Firefox inexistente e sem `cookies.json` | Logue no Firefox **ou** crie `cookies.json` |
| Label "Claude: idle" | Todos os percentuais estão em 0% | Comportamento esperado quando não há consumo |
| Erro `ModuleNotFoundError: curl_cffi` | Pip rodou em Python errado | Rode `pip install --user curl_cffi` com o mesmo Python do widget |

## Desinstalar

```bash
~/.local/share/claude-widget/uninstall.sh
```

## Aviso

Este projeto usa uma API privada não documentada do `claude.ai`. Não há
garantia de funcionamento; mudanças no backend da Anthropic podem quebrar o
widget a qualquer momento. Use por sua conta e risco.

## Licença

MIT.
