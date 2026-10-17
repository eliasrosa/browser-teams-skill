#!/usr/bin/env python3
"""
Lista os chats do Teams com última mensagem depois de uma data, lendo o banco local
(IndexedDB 'Teams:conversation-manager' -> 'conversations'). Não abre nenhum chat.

Uso: python3 list_changed.py [desde="YYYY-MM-DD HH:MM"]  (default: 4 dias atrás)
Saída (TSV, mais recente primeiro): ultima_msg_BRT <TAB> conversationId <TAB> titulo

Pré-requisito: playwright-cli conectado com a aba do Teams como "current" (attach.sh).
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))

def get_desde(arg: str | None) -> tuple[str, int]:
    if not arg:
        dt = datetime.now(BRT) - timedelta(days=4)
        dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(arg, fmt).replace(tzinfo=BRT)
                break
            except ValueError:
                pass
        else:
            print(f'data inválida (use "YYYY-MM-DD" ou "YYYY-MM-DD HH:MM"): {arg}', file=sys.stderr)
            sys.exit(1)
    return dt.strftime('%Y-%m-%d %H:%M'), int(dt.timestamp() * 1000)

JS_TEMPLATE = r"""
async (page) => {{
  return await page.evaluate(async (desdeMs) => {{
    const name = (await indexedDB.databases()).map(d => d.name)
      .find(n => n && n.startsWith('Teams:conversation-manager'));
    if (!name) return {{ erro: 'banco conversation-manager não encontrado' }};

    const db = await new Promise((res, rej) => {{
      const q = indexedDB.open(name);
      q.onsuccess = () => res(q.result);
      q.onerror   = () => rej(q.error);
    }});
    const all = await new Promise(res => {{
      const q = db.transaction('conversations', 'readonly')
                  .objectStore('conversations').getAll();
      q.onsuccess = () => res(q.result || []);
      q.onerror   = () => res([]);
    }});
    db.close();

    return all
      .filter(c => String(c.id || '').startsWith('19:') && Number(c.lastMessageTimeUtc || 0) > desdeMs)
      .map(c => {{
        const ct = c.chatTitle;
        const title = (ct && typeof ct === 'object')
          ? (ct.shortTitle || '')
          : (ct || (c.threadProperties || {{}}).topic || '');
        return {{ id: String(c.id), t: Number(c.lastMessageTimeUtc || 0), title: String(title) }};
      }})
      .sort((a, b) => b.t - a.t);
  }}, {desde_ms});
}}
"""

def parse_result(raw: str) -> list:
    s = raw.find('### Result')
    e = raw.find('### Ran Playwright code')
    if s < 0:
        print('nenhum resultado encontrado na saída do playwright-cli', file=sys.stderr)
        sys.exit(1)
    body = raw[s + len('### Result'):e].strip() if e >= 0 else raw[s + len('### Result'):].strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        print(f'erro ao parsear JSON: {exc}\ntrecho: {body[:300]}', file=sys.stderr)
        sys.exit(1)

def main():
    desde_str, desde_ms = get_desde(sys.argv[1] if len(sys.argv) > 1 else None)
    js = JS_TEMPLATE.format(desde_ms=desde_ms)

    result = subprocess.run(
        ['playwright-cli', 'run-code', js],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f'playwright-cli falhou: {result.stderr}', file=sys.stderr)
        sys.exit(1)

    data = parse_result(result.stdout)

    if isinstance(data, dict) and 'erro' in data:
        print(data['erro'], file=sys.stderr)
        sys.exit(1)

    for item in data:
        ts  = datetime.fromtimestamp(item['t'] / 1000, BRT).strftime('%d/%m/%Y %H:%M')
        title = ' '.join(str(item['title']).split())
        print(f"{ts}\t{item['id']}\t{title}")

if __name__ == '__main__':
    main()
