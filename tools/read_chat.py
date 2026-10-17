#!/usr/bin/env python3
"""
Lê as mensagens de um chat do Teams pelo cache local (IndexedDB) ou pela rede.

Uso:
  python3 read_chat.py <conversationId> <saida.txt> [desde=YYYY-MM-DD] [--rede|--so-cache]

Argumentos:
  conversationId  ID do chat (19:...)
  saida.txt       Arquivo de saída (criado/sobrescrito)
  desde           Data de corte, formato YYYY-MM-DD (default: 30 dias atrás)
  --rede          Forçar leitura pela rede (abre o chat, marca como lido)
  --so-cache      Nunca abrir o chat (pula se sem cache)

Saída por linha: DD/MM/YYYY HH:MM — Autor: texto
Primeira linha: # fonte: cache | rede | motivo de skip
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from session import cli as playwright_cli, parse_playwright_result

BRT = timezone(timedelta(hours=-3))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_args():
    args = sys.argv[1:]
    if len(args) < 2:
        print('Uso: read_chat.py <conversationId> <saida.txt> [desde=YYYY-MM-DD] [--rede|--so-cache]', file=sys.stderr)
        sys.exit(1)

    conv_id  = args[0]
    saida    = Path(args[1])
    desde    = None
    modo     = 'auto'   # auto | rede | so-cache

    for a in args[2:]:
        if a == '--rede':
            modo = 'rede'
        elif a == '--so-cache':
            modo = 'so-cache'
        elif re.match(r'^\d{4}-\d{2}-\d{2}$', a):
            desde = a

    if not re.match(r'^19:', conv_id):
        print(f'conversationId inválido (deve começar com "19:"): {conv_id}', file=sys.stderr)
        sys.exit(1)

    if desde is None:
        dt = datetime.now(BRT) - timedelta(days=30)
        desde = dt.strftime('%Y-%m-%d')

    return conv_id, saida, desde, modo


def run_js(js: str) -> str:
    return playwright_cli(["run-code", js])


def parse_result(raw: str):
    return parse_playwright_result(raw)


def format_msg(msg: dict) -> str | None:
    ts_raw = msg.get('originalArrivalTime') or msg.get('composetime') or ''
    try:
        ts = datetime.fromisoformat(ts_raw.replace('Z', '+00:00')).astimezone(BRT)
        ts_str = ts.strftime('%d/%m/%Y %H:%M')
    except Exception:
        ts_str = '??/??/???? ??:??'

    # autor: imdisplayname > displayName > from.user.displayName
    autor = (msg.get('imdisplayname')
             or msg.get('displayName')
             or (msg.get('from') or {}).get('user', {}).get('displayName', '')
             or 'Desconhecido')

    # corpo: content (HTML) → texto plano
    content = msg.get('content') or ''
    content = re.sub(r'<[^>]+>', '', content)
    content = content.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ')
    content = ' '.join(content.split())
    if not content:
        return None

    return f'{ts_str} — {autor}: {content}'


# ---------------------------------------------------------------------------
# Leitura por cache (IndexedDB Teams:replychain-manager)
# ---------------------------------------------------------------------------

JS_CACHE = r"""
async (page) => {{
  return await page.evaluate(async (convId, desdeMs) => {{
    const name = (await indexedDB.databases()).map(d => d.name)
      .find(n => n && n.startsWith('Teams:replychain-manager'));
    if (!name) return {{ erro: 'banco replychain-manager não encontrado' }};

    const db = await new Promise((res, rej) => {{
      const q = indexedDB.open(name);
      q.onsuccess = () => res(q.result);
      q.onerror   = () => rej(q.error);
    }});

    const store = db.transaction('replychains', 'readonly').objectStore('replychains');
    const all   = await new Promise(res => {{
      const q = store.getAll();
      q.onsuccess = () => res(q.result || []);
      q.onerror   = () => res([]);
    }});
    db.close();

    const msgs = [];
    for (const chain of all) {{
      if (!String(chain.id || '').startsWith(convId)) continue;
      for (const msg of Object.values(chain.messageMap || {{}})) {{
        const t = Number(new Date(msg.originalArrivalTime || msg.composetime || 0));
        if (t < desdeMs) continue;
        if (msg.messageType === 'RichText/Html' || msg.messageType === 'text') {{
          msgs.push(msg);
        }}
      }}
    }}
    return msgs;
  }}, {conv_id!r}, {desde_ms});
}}
"""

# ---------------------------------------------------------------------------
# Leitura pela rede (abre o chat pelo deep link e captura a API)
# ---------------------------------------------------------------------------

JS_REDE = r"""
async (page) => {{
  const url = 'https://teams.cloud.microsoft/l/chat/{conv_id}/conversations';
  await page.evaluate(u => window.open(u, '_blank'), url);
  await page.waitForTimeout(3000);

  // espera a aba do deep link ficar ativa
  const resp = await page.waitForResponse(
    r => r.url().includes('/messages') && r.url().includes('{conv_id}'),
    {{ timeout: 15000 }}
  ).catch(() => null);
  if (!resp) return {{ erro: 'timeout aguardando resposta de mensagens do Teams' }};

  const body = await resp.json().catch(() => null);
  if (!body) return {{ erro: 'resposta de mensagens não é JSON' }};

  const desdeMs = {desde_ms};
  return (body.value || []).filter(m => {{
    const t = Number(new Date(m.originalArrivalTime || m.composetime || 0));
    return t >= desdeMs && (m.messageType === 'RichText/Html' || m.messageType === 'text');
  }});
}}
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    conv_id, saida, desde, modo = parse_args()

    dt_desde = datetime.strptime(desde, '%Y-%m-%d').replace(tzinfo=BRT)
    desde_ms  = int(dt_desde.timestamp() * 1000)

    saida.parent.mkdir(parents=True, exist_ok=True)

    # --- tenta cache primeiro (a menos que --rede forçado) ---
    msgs_raw = None
    fonte    = 'cache'

    if modo != 'rede':
        js = JS_CACHE.format(conv_id=conv_id, desde_ms=desde_ms)
        data = parse_result(run_js(js))
        if data is None:
            fonte = 'cache-erro'
        elif isinstance(data, dict) and 'erro' in data:
            fonte = f'cache-indisponível ({data["erro"]})'
        elif isinstance(data, list) and len(data) == 0:
            fonte = 'cache-vazio'
        else:
            msgs_raw = data

    # --- fallback rede (se auto e cache vazio/erro, ou --rede) ---
    if msgs_raw is None and modo == 'rede':
        js = JS_REDE.format(conv_id=conv_id, desde_ms=desde_ms)
        data = parse_result(run_js(js))
        if data is None or (isinstance(data, dict) and 'erro' in data):
            err = data.get('erro', 'erro desconhecido') if isinstance(data, dict) else 'parse falhou'
            saida.write_text(f'# fonte: rede-erro — {err}\n', encoding='utf-8')
            sys.exit(0)
        msgs_raw = data
        fonte = 'rede'

    # --- sem cache e --so-cache ---
    if msgs_raw is None:
        saida.write_text(f'# fonte: sem-cache — abrir manualmente\n', encoding='utf-8')
        sys.exit(0)

    # --- formatar e gravar ---
    linhas = [f'# fonte: {fonte}']
    for msg in msgs_raw:
        linha = format_msg(msg)
        if linha:
            linhas.append(linha)

    saida.write_text('\n'.join(linhas) + '\n', encoding='utf-8')
    print(f'{len(linhas) - 1} mensagens gravadas em {saida}')


if __name__ == '__main__':
    main()
