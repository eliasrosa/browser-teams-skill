# browser-teams-skill

Skill do [Kiro Crew](https://kiro.dev) para automação do Microsoft Teams via CDP.

Lê chats, lista não lidos e atualiza notas de acompanhamento — tudo pelo
cache local do browser, sem abrir chats nem marcar mensagens como lidas.

Depende do [`browser-automation-skill`](https://github.com/eliasrosa/browser-automation-skill)
para a conexão base com o Chrome via CDP.

## O que faz

- **Lista não lidos** por prioridade: @mentions → 1:1 → grupos (`list_unread.py`)
- **Lista chats com mensagens novas** desde uma data (`list_changed.py`)
- **Lê mensagens** pelo cache IndexedDB sem abrir o chat (`read_chat.py`)
- **Triagem interativa** via `$teams-inbox`: resumo por categoria, escolha de frente, atualização de notas
- **Rotina diária silenciosa**: atualiza só o que é novo, notifica com resumo

## Instalação

```bash
# 1. Pré-requisito: browser-automation-skill (base CDP)
git clone https://github.com/eliasrosa/browser-automation-skill \
  ~/.kiro/crew/skills/browser-automation

# 2. Esta skill
git clone https://github.com/eliasrosa/browser-teams-skill \
  ~/.kiro/skills/teams-inbox
```

**Configuração do Chrome (uma vez):**
1. Abrir o Chrome normalmente
2. Ir em `chrome://inspect/#remote-debugging` e habilitar
3. Instalar a [extensão do Playwright](https://chromewebstore.google.com/detail/playwright-extension/mmlmfjhmonkocbjadbfplnigmagldckm)

## Uso

Basta pedir ao agente:

- `$teams-inbox` — triagem interativa dos não lidos
- "Lê meus chats do Teams dos últimos 4 dias"
- "Atualiza as notas do Teams"
- "O que tenho não lido no Teams?"

## Ferramentas (Python 3.10+, sem dependências externas além do `playwright-cli`)

| Script | Uso |
|--------|-----|
| `tools/attach.py [-s <sessao>]` | Conecta ao Chrome e seleciona a aba do Teams |
| `tools/list_unread.py` | Lista não lidos classificados por prioridade |
| `tools/list_changed.py [desde="YYYY-MM-DD HH:MM"]` | Lista chats com msg nova |
| `tools/read_chat.py <id> <saida.txt> [desde] [--rede\|--so-cache]` | Lê mensagens |

## Estrutura

```
browser-teams-skill/
├── SKILL.md          # Instruções completas para o agente
├── README.md         # Este arquivo
├── LICENSE           # MIT
├── runbooks/
│   └── teams-mapa.md # Estrutura da UI do Teams, seletores, IndexedDB
└── tools/
    ├── attach.py     # Conectar ao Chrome (delega ao browser-automation-skill)
    ├── list_unread.py
    ├── list_changed.py
    └── read_chat.py
```

## Regras de segurança

- Nunca abre chats automaticamente (usa sempre `--so-cache` na rotina)
- Não lê `Teams:auth` nem localStorage (contêm credenciais)
- Nunca envia mensagem sem confirmação explícita do usuário
- Scripts não contêm IDs, nomes ou dados de ambiente — ficam nos steerings do usuário

## Relacionados

- [browser-automation-skill](https://github.com/eliasrosa/browser-automation-skill) — base CDP
- [playwright-cli](https://github.com/anthropics/anthropic-tools) — CLI por baixo
- [Kiro Crew](https://kiro.dev) — plataforma de agentes autônomos

## Licença

MIT
