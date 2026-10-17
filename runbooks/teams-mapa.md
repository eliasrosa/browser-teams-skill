# Microsoft Teams — Mapa de automação

> Estrutura da UI, seletores e padrões técnicos para automação via CDP.
> Só técnica — nenhum dado de conta, grupo ou contato vai aqui.
> IDs reais ficam nos steerings/notas do próprio usuário.
>
> Regras gerais de conexão (attach, sessões, navegação) estão no
> `browser-automation-skill` (skill pai).

## Regras de uso no Teams

1. **Filtros e busca desligados por padrão.** Find in chat (Ctrl+F), busca global,
   filtros (Date, From, etc.) e a aba Unread só são ativados para pesquisar. Ao terminar,
   fechar o painel, limpar os filtros e voltar à aba Chats normal.
2. **Abrir um chat marca as mensagens como lidas.** Para levantar pendências sem
   alterar o estado de leitura, usar o cache IndexedDB (ver abaixo), não abrir o chat.
3. **Não responder sem pedido.** Ler e resumir não autoriza enviar. Enviar só com
   confirmação explícita do texto pelo usuário.

## Referência Rápida — operações

| Operação | Como |
|---|---|
| Ler o chat aberto | `evaluate` + `innerText` em `[data-tid="app-layout-area--main"]` |
| Enviar mensagem | abrir chat → `fill` no textbox → `click` no botão Send |
| @menção | digitar `@Nome` → aguardar listbox Suggestions → `click` na option |
| Buscar no chat ativo | `Ctrl+F` → digitar no searchbox → `Enter` |
| Busca global | `Ctrl+Alt+E` → combobox "Search or ask Copilot" |
| Filtrar o sidebar | textbox "Filter by person or chat name" (limpar ao terminar) |
| Listar itens de chat | `querySelectorAll('span[id^="title-chat-list-item_"]')` |
| Ler sem marcar como lido | cache IndexedDB `Teams:replychain-manager` |

## Estrutura da UI

### Sidebar do Chat — controles

| Elemento | Seletor snapshot |
|---|---|
| Novo chat/mensagem | `button "New message"` |
| Filtro da lista | `textbox "Filter by person or chat name"` |
| Fechar filtro | `button "Close filter text box"` |
| Aba Não lidos | `button "Unread"` |
| Aba Chats | `button "Chats"` |
| Aba Meeting chats | `button "Meeting chats"` |
| Mais opções da lista | `button "More list options"` |

### Abas e quick views

- **Chats**: lista geral. Pode ter pastas/seções custom (Favorites + pastas do usuário).
- **Unread**: lista **todos** os não lidos, inclusive chats mutados antigos.
- **Meeting chats**: só conversas de reunião.
- Dentro de Chats, expandindo: **Drafts**, **Mentions**, **Favorites**.

### Editor de mensagem

| Elemento | Seletor DOM | Seletor snapshot |
|---|---|---|
| Campo de texto | `[data-tid="app-layout-area--main"] [role="textbox"]` | `textbox "Type a message"` |
| Botão enviar | `button[aria-label*="Send"]` | `button "Send (Ctrl+Enter)"` |

## Identificação de chats (`conversationId`)

Cada item do sidebar é um `span` com `id="title-chat-list-item_<conversationId>"`. O
`conversationId` é **estável entre sessões** — preferir ele ao nome exibido.

Três formatos:

| Tipo | Formato |
|---|---|
| Chat 1:1 (pessoa ou bot) | `19:<userIdA>_<userIdB>@unq.gbl.spaces` |
| Grupo / canal | `19:<hash>@thread.v2` |
| Meeting chat | `19:meeting_<base64>@thread.v2` |

**Gotcha**: os `span[id^="title-chat-list-item_"]` só existem na DOM com as pastas
expandidas e sem o filtro Unread ativo. Se a extração vier vazia, expandir as pastas.

## Padrões técnicos

### Ler o chat aberto

```javascript
page.evaluate(() => document.querySelector('[data-tid="app-layout-area--main"]').innerText)
```

**Gotchas:**
- `mouse.wheel` não rola o chat: o scroll fica numa div interna.
- O Teams **virtualiza** as mensagens: rolar descarrega as antigas do DOM.
  O `innerText` pega só o buffer carregado.

### Ler sem marcar como lido (IndexedDB)

```
DB    : Teams:replychain-manager:…
Store : replychains
Key   : [conversationId, replyChainId]
Valor : cada registro tem um messageMap com as mensagens
```

Leitura não abre o chat, não toca a tela — pode rodar em paralelo.

### Listar não lidos (IndexedDB)

```
DB    : Teams:conversation-manager:…
Store : conversations
Campos úteis: id, chatType/threadType, unreadCount, mentionCount,
              lastMessageTimeUtc, chatTitle (objeto: shortTitle, displayName)
```

### Abrir um chat (somente quando necessário)

```javascript
// Por conversationId (preferido)
document.getElementById('title-chat-list-item_' + id)
  ?.closest('[role="treeitem"]')?.click();
```

### Deep link para um chat

```
https://teams.cloud.microsoft/l/chat/<conversationId>/conversations
```

Abrir com `window.open(url, '_blank')` (nunca `goto`/`tab-new`).

### Capturar resposta de API de mensagens

```javascript
const r = await page.waitForResponse(u => u.url().includes('/messages'));
return await r.json();
```

## Dois tipos de busca no Teams

| Busca | Atalho | Escopo |
|---|---|---|
| Find in chat | Ctrl+F | Local ao chat aberto |
| Busca global | Ctrl+Alt+E | Todos os chats, arquivos, pessoas |

Find in chat expõe filtros por data (From/To), pessoa (From), tipo (Messages/Attachment/Mentions).
Usar `type` (não `fill`) para disparar a busca. Fechar ao terminar.
