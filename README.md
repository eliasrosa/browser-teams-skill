# browser-teams-skill

Skill do [Kiro Crew](https://kiro.dev) para automação do Microsoft Teams via CDP.

Lê chats, lista não lidos e atualiza notas de acompanhamento — tudo pelo
cache local do browser, sem abrir chats nem marcar mensagens como lidas.

Depende do [`browser-automation-skill`](https://github.com/eliasrosa/browser-automation-skill)
para a conexão base com o Chrome via CDP.

## O que faz

- **Mapeia contatos** do Teams para banco SQLite local (`map_contacts.py`)
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

## Onboarding — primeira execução

Com o Teams aberto no Chrome, rodar uma vez para mapear todos os chats:

```bash
python3 ~/.kiro/skills/teams-inbox/tools/attach.py
python3 ~/.kiro/skills/teams-inbox/tools/map_contacts.py
```

Saída esperada:
```
Lendo IndexedDB do Teams...
✓ /home/<usuario>/.kiro/skills/teams-inbox/.data/contacts.db
  87 novos  |  0 atualizados  |  87 total no banco
  1:1: 28
  grupo: 31
  meeting: 28
```

O banco fica em `.data/contacts.db` — pasta **gitignored**, não é sobrescrita em `git pull`.
Rodar novamente a qualquer momento para incluir chats novos. Os outros scripts
(`list_unread.py`, `list_changed.py`) também atualizam o banco automaticamente.

Para inspecionar sem gravar:
```bash
python3 tools/map_contacts.py --dry-run
```

## Uso

Basta pedir ao agente:

- `$teams-inbox` — triagem interativa dos não lidos
- "Lê meus chats do Teams dos últimos 4 dias"
- "Atualiza as notas do Teams"
- "O que tenho não lido no Teams?"

## Ferramentas (Python 3.10+, sem dependências externas além do `playwright-cli`)

| Script | Uso |
|--------|-----|
| `tools/map_contacts.py [--dry-run]` | **Onboarding**: mapeia todos os chats para `.data/contacts.db` |
| `tools/attach.py [-s <sessao>]` | Conecta ao Chrome e seleciona a aba do Teams |
| `tools/list_unread.py` | Lista não lidos por prioridade (atualiza banco) |
| `tools/list_changed.py [desde="YYYY-MM-DD HH:MM"]` | Lista chats com msg nova (atualiza banco) |
| `tools/read_chat.py <id> <saida.txt> [desde] [--rede\|--so-cache]` | Lê mensagens |
| `tools/config.py [set <chave> <valor>]` | Lê/grava `.data/config.json` |
| `tools/db.py` | Helper interno: SQLite de contatos (não usar diretamente) |

## Banco de contatos local

Os scripts mantêm um banco SQLite em `.data/contacts.db` (gitignored):

```
contacts (id PK, tipo, nome, ultima_msg_ms, unread, mentions, atualizado_em)
```

- Persiste entre `git pull` — dados do usuário nunca são sobrescritos
- Chats arquivados ou removidos do Teams são preservados
- Alimentado pelo `map_contacts.py` (completo) e pelos outros scripts (incremental)

## Configuração local (`.data/config.json`)

Preferências do usuário — gitignored, não sobrescritas em `git pull`.

```bash
python3 tools/config.py                            # ver configuração atual
python3 tools/config.py set notes_dir ~/vault/Teams  # alterar notes_dir
```

| Campo | Default | Descrição |
|-------|---------|-----------|
| `notes_dir` | `<skill>/.data/notes/` | Onde gravar as notas de leitura (MDs por chat) |
| `message_prefix` | `🤖 ` | Prefixo de toda mensagem enviada pelo agente |
| `send_key` | `Ctrl+Enter` | Atalho para enviar no Teams web. Mudar para `Enter` se Settings > General > "Send messages on Enter" estiver ativo |

## Envio de mensagens

O agente consegue enviar mensagens no Teams via CDP. Toda mensagem sai com o prefixo configurado:

```
🤖 [corpo da mensagem]
```

**Regra:** nunca envia sem confirmação explícita do usuário. A mensagem é enviada no nome do usuário logado no Chrome — não como "Estagiário".

## Estrutura

```
browser-teams-skill/
├── SKILL.md             # Instruções completas para o agente
├── README.md            # Este arquivo
├── LICENSE              # MIT
├── .gitignore           # Exclui .data/ (dados locais do usuário)
├── runbooks/
│   └── teams-mapa.md    # Estrutura da UI do Teams, seletores, IndexedDB
└── tools/
    ├── map_contacts.py  # Onboarding: mapeia chats → .data/contacts.db
    ├── attach.py        # Conectar ao Chrome (delega ao browser-automation-skill)
    ├── db.py            # Helper SQLite compartilhado
    ├── list_unread.py   # Lista não lidos classificados
    ├── list_changed.py  # Lista chats com msg nova
    └── read_chat.py     # Lê mensagens pelo cache IndexedDB
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
