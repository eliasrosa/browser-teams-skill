---
name: teams-inbox
description: Use when the user says '$teams-inbox', 'ver não lidos do Teams', 'o que tenho não lido no Teams', 'abrir inbox do Teams', 'ler chats do Teams', 'atualizar notas do Teams' or asks to read, triage or update unread Teams messages. Requires browser-automation-skill installed (CDP base).
inclusion: auto
version: 2026-10-17
---

# browser-teams-skill — Teams via browser CDP

Skill especializada para Microsoft Teams. Lê chats, lista não lidos e atualiza notas
no vault do usuário. Depende do [`browser-automation-skill`][bas] para a base CDP.

[bas]: https://github.com/eliasrosa/browser-automation-skill

## Pré-requisitos

1. **Chrome com remote debugging** ativo (`chrome://inspect/#remote-debugging`)
2. **Extensão Playwright** instalada no Chrome
3. **`browser-automation-skill`** instalada:
   ```bash
   git clone https://github.com/eliasrosa/browser-automation-skill \
     ~/.kiro/crew/skills/browser-automation
   ```
4. **`browser-teams-skill`** instalada:
   ```bash
   git clone https://github.com/eliasrosa/browser-teams-skill \
     ~/.kiro/skills/teams-inbox
   ```

5. **Mapeamento inicial** (uma vez — com o Teams aberto no Chrome):
   ```bash
   python3 ~/.kiro/skills/teams-inbox/tools/attach.py
   python3 ~/.kiro/skills/teams-inbox/tools/map_contacts.py
   # Exemplo de saída:
   # ✓ /home/<usuario>/.kiro/skills/teams-inbox/.data/contacts.db
   #   87 novos  |  0 atualizados  |  87 total no banco
   #   1:1: 28
   #   grupo: 31
   #   meeting: 28
   ```
   O banco fica em `teams-inbox/.data/contacts.db` (gitignored — não é sobrescrito em `git pull`).
   Rodar novamente a qualquer momento para atualizar com novos chats.

## Referência Rápida

| Script | O que faz |
|--------|-----------|\n| `tools/map_contacts.py [--dry-run]` | **Onboarding**: varre todos os chats e grava `.data/contacts.db` |
| `tools/attach.py [-s <sessao>]` | Conecta ao Chrome + seleciona aba do Teams |
| `tools/list_unread.py` | Lista não lidos por prioridade: mention → 1:1 → grupo |
| `tools/list_changed.py [desde="YYYY-MM-DD HH:MM"]` | Lista chats com msg nova desde uma data |
| `tools/read_chat.py <id> <saida.txt> [desde] [--rede\|--so-cache]` | Lê mensagens do chat |
| `tools/db.py` | Helper interno: leitura e upsert do banco de contatos |
| `tools/config.py [set <chave> <valor>]` | Lê/grava `.data/config.json` (notes_dir, etc.) |

### Banco de contatos (`.data/contacts.db`)

Arquivo SQLite local em `~/.kiro/skills/teams-inbox/.data/contacts.db`.
Persiste entre atualizações da skill (`.gitignore` exclui `.data/`).

```
contacts (id PK, tipo, nome, ultima_msg_ms, unread, mentions, atualizado_em)
```

- `list_unread.py` e `list_changed.py` atualizam o banco automaticamente ao rodar
- Chats que o Teams não retornar mais (arquivados) são preservados no banco
- Usuário novo: rodar `map_contacts.py` uma vez para popular

### Configuração local (`.data/config.json`)

Preferências do usuário — gitignored, não sobrescritas em `git pull`. Gerenciadas por `tools/config.py`.

| Campo | Default | Descrição |
|-------|---------|-----------|
| `notes_dir` | `<skill>/.data/notes/` | Diretório das notas de leitura (MDs por chat) |

```bash
# Ver configuração atual
python3 tools/config.py

# Alterar (ex: apontar para vault Obsidian)
python3 tools/config.py set notes_dir ~/dev/obsidian-vault/Cogna/Teams
```

Estrutura criada automaticamente dentro de `notes_dir`:
```
notes_dir/
├── 1-1/       ← conversas oneOnOne
├── grupos/    ← canais e grupos
└── reunioes/  ← chats de meetings
```

Usuário novo: default é `<skill>/.data/notes/` (portável, sem dependência externa).
Com vault Obsidian: configurar `notes_dir` apontando para a pasta do Teams.

Saída do `list_unread.py` (TSV):
```
categoria  unread  mentions  conversationId  titulo
mention    3       2         19:abc@...      Pedro Rago
1:1        5       0         19:def@...      Wisandro Lima
grupo      8       0         19:ghi@...      Squad GW Daily
```

## Fluxo — triagem interativa (`$teams-inbox`)

### 1 — conectar
```bash
python3 tools/attach.py
```
Se falhar (Chrome fechado, sem remote debugging, sem aba do Teams): informar o motivo
e encerrar. Não continuar.

### 2 — listar não lidos
```bash
python3 tools/list_unread.py
```
Vazio → "Teams: nenhuma mensagem não lida." e encerrar.

### 3 — apresentar resumo e perguntar por onde começar

Formato do resumo (máximo 3 itens por categoria; agrupar o resto em "... (mais N)"):

```
📬 Teams — não lidos agora

📌 @mentions (2)
  • Pedro Rago (3 msgs)
  • Squad GW Daily (1 msg)

💬 1:1 (4)
  • Wisandro Lima (5 msgs)
  • ...

👥 Grupos (3)
  • Multimeios (8 msgs)
  • ...

Por qual frente/categoria você quer começar?
```

Usar `[OPTIONS:]` com as categorias disponíveis + "Mostrar todos".

### 4 — ler e resumir o(s) chat(s) escolhido(s)

Para cada chat:

1. Localizar a nota pelo `conversation_id` no vault:
   ```bash
   grep -rl "conversation_id: <id>" ~/.../Teams/
   ```
   - Nota existe → ler `ultima_leitura` do frontmatter.
   - Não existe → usar 30 dias atrás.

2. Ler (só cache, nunca abre o chat):
   ```bash
   python3 tools/read_chat.py <id> "$KIROCREW_SCRATCH/teams-inbox/<n>.txt" \
     <ultima_leitura YYYY-MM-DD> --so-cache
   ```

3. Primeira linha da saída indica a fonte (`# fonte: cache | sem-cache | rede-erro`).
   - `sem-cache` → reportar "sem cache local — abrir manualmente" e pular.

4. Resumir e atualizar a nota:
   - Bullets no **Contexto atual** (data em negrito)
   - `[x]` em pendências resolvidas
   - Pendências novas
   - Nova entrada no topo do **Log de leitura**: `DD/MM/YYYY HH:MM — lido de <antiga> até <última msg> (teams-inbox)`
   - Atualizar `ultima_leitura` no frontmatter

5. Perguntar se quer responder ou ir ao próximo. Nunca responder sem pedido explícito.

### 5 — atualizar `_painel.md` e limpar
```bash
rm -rf "$KIROCREW_SCRATCH/teams-inbox/"
```

## Fluxo — rotina diária (atualização silenciosa)

Agenda sugerida: dias úteis às 08:30 via cron.

```
1. attach.py
2. list_changed.py "$(date -d '4 days ago' '+%Y-%m-%d')"
3. Para cada chat: nota pelo conversation_id; pula se ultima_msg <= ultima_leitura
4. read_chat.py <id> <saida> <ultima_leitura> --so-cache → atualiza nota
5. Atualiza _painel.md
6. send_message com resumo
```

## Estrutura das notas

Pasta: `~/.../Teams/` (path configurado nos steerings do usuário)

Subpastas:
- `1-1/` — conversas oneOnOne
- `Grupos/` — grupos e canais
- `Reunioes/` — chats de meeting

Frontmatter mínimo:
```yaml
---
conversation_id: 19:xxxx
ultima_leitura: "YYYY-MM-DD HH:MM"
prioridade: A | B | C
---
```

## Regras

- **Nunca abrir o chat** sem autorização explícita (sempre `--so-cache` na rotina)
- Não ler `Teams:auth` nem localStorage (contêm credenciais)
- Nunca enviar mensagem sem confirmação explícita do texto pelo usuário
- Não incluir nas notas: e-mails, telefones, CPF/CNPJ, dados de clientes, IPs, tokens
- Usar "o usuário" em notas e resumos compartilháveis (não nome pessoal)
- Não inventar: só o que as mensagens dizem

## Erros Comuns

| Erro | Causa | Ação |
|------|-------|------|
| `DevToolsActivePort ausente` | Chrome fechado | Pedir ao usuário abrir o Chrome |
| `nenhuma aba do Teams aberta` | Teams não está no Chrome | Pedir ao usuário abrir o Teams |
| `list_unread.py` retorna vazio | Nenhum não lido ou banco não carregado | Recarregar aba do Teams |
| `# fonte: sem-cache` em read_chat | Sem cache local para este chat | Reportar "abrir manualmente" |
| `banco conversation-manager não encontrado` | Teams não inicializou o IndexedDB | Aguardar Teams carregar |
