#!/usr/bin/env python3
"""
Lista os chats do Teams com mensagens não lidas, classificados por prioridade:
  1) mention  — mentionCount > 0
  2) 1:1      — tipo oneOnOne
  3) grupo    — group, meeting, etc.

Uso: python3 list_unread.py
Saída (TSV, mais recente primeiro por categoria):
  categoria <TAB> unread <TAB> mentions <TAB> conversationId <TAB> titulo

Pré-requisito: playwright-cli conectado com a aba do Teams como "current" (attach.sh).
"""

import json
import subprocess
import sys

JS = r"""
async (page) => {
  return await page.evaluate(async () => {
    const name = (await indexedDB.databases()).map(d => d.name)
      .find(n => n && n.startsWith('Teams:conversation-manager'));
    if (!name) return { erro: 'banco conversation-manager não encontrado' };

    const db = await new Promise((res, rej) => {
      const q = indexedDB.open(name);
      q.onsuccess = () => res(q.result);
      q.onerror   = () => rej(q.error);
    });
    const all = await new Promise(res => {
      const q = db.transaction('conversations', 'readonly')
                  .objectStore('conversations').getAll();
      q.onsuccess = () => res(q.result || []);
      q.onerror   = () => res([]);
    });
    db.close();

    return all
      .filter(c => String(c.id || '').startsWith('19:'))
      .filter(c => (c.unreadCount || 0) > 0 || (c.mentionCount || 0) > 0)
      .map(c => {
        const ct = c.chatTitle;
        const title = (ct && typeof ct === 'object')
          ? (ct.shortTitle || ct.displayName || '')
          : (ct || (c.threadProperties || {}).topic || c.id || '');
        return {
          id:       String(c.id),
          title:    String(title),
          tipo:     String(c.chatType || c.threadType || 'group').toLowerCase(),
          unread:   Number(c.unreadCount  || 0),
          mentions: Number(c.mentionCount || 0),
          lastMs:   Number(c.lastMessageTimeUtc || 0),
        };
      });
  });
}
"""

def categoria(item: dict) -> str:
    if item['mentions'] > 0:
        return 'mention'
    if 'oneonone' in item['tipo'] or item['tipo'] == '1:1':
        return '1:1'
    return 'grupo'

def sort_key(item: dict) -> tuple:
    order = {'mention': 0, '1:1': 1, 'grupo': 2}
    return (order.get(categoria(item), 9), -item['lastMs'])

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
    result = subprocess.run(
        ['playwright-cli', 'run-code', JS],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f'playwright-cli falhou: {result.stderr}', file=sys.stderr)
        sys.exit(1)

    data = parse_result(result.stdout)

    if isinstance(data, dict) and 'erro' in data:
        print(data['erro'], file=sys.stderr)
        sys.exit(1)

    data.sort(key=sort_key)

    for item in data:
        cat   = categoria(item)
        title = ' '.join(str(item['title']).split()) or item['id']
        print(f"{cat}\t{item['unread']}\t{item['mentions']}\t{item['id']}\t{title}")

if __name__ == '__main__':
    main()
