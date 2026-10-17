#!/usr/bin/env python3
"""
Lista os chats do Teams com mensagens não lidas, classificados por prioridade:
  1) mention  — mentionCount > 0
  2) 1:1      — tipo oneOnOne
  3) grupo    — group, meeting, etc.

Atualiza automaticamente .data/contacts.db quando encontrar chat novo ou renomeado.

Uso: python3 list_unread.py
Saída (TSV, mais recente primeiro por categoria):
  categoria <TAB> unread <TAB> mentions <TAB> conversationId <TAB> titulo

Pré-requisito: playwright-cli conectado com a aba do Teams como "current" (attach.py).
"""

import json
import subprocess
import sys
from pathlib import Path

# helper local
sys.path.insert(0, str(Path(__file__).parent))
import db as contacts_db

JS = r"""
async (page) => {
  return await page.evaluate(async () => {
    const name = (await indexedDB.databases()).map(d => d.name)
      .find(n => n && n.startsWith('Teams:conversation-manager'));
    if (!name) return { erro: 'banco conversation-manager não encontrado' };

    const dbh = await new Promise((res, rej) => {
      const q = indexedDB.open(name);
      q.onsuccess = () => res(q.result);
      q.onerror   = () => rej(q.error);
    });
    const all = await new Promise(res => {
      const q = dbh.transaction('conversations', 'readonly')
                   .objectStore('conversations').getAll();
      q.onsuccess = () => res(q.result || []);
      q.onerror   = () => res([]);
    });
    dbh.close();

    return all
      .filter(c => String(c.id || '').startsWith('19:'))
      .filter(c => (c.unreadCount || 0) > 0 || (c.mentionCount || 0) > 0)
      .map(c => {
        const ct = c.chatTitle;
        const nome = (ct && typeof ct === 'object')
          ? (ct.shortTitle || ct.displayName || '')
          : (ct || (c.threadProperties || {}).topic || c.id || '');
        // tipo inferido pelo padrao do ID (chatType/threadType vazios no IndexedDB)
        const id_str = String(c.id || '');
        const tipo = id_str.includes('@unq.gbl.spaces') ? '1:1'
                   : id_str.includes('meeting_')         ? 'meeting'
                   : 'grupo';
        return {
          id:            String(c.id),
          tipo,
          nome:          String(nome).trim() || String(c.id),
          ultima_msg_ms: Number(c.lastMessageTimeUtc || 0),
          unread:        Number(c.unreadCount  || 0),
          mentions:      Number(c.mentionCount || 0),
        };
      });
  });
}
"""


def categoria(item: dict) -> str:
    if item['mentions'] > 0:
        return 'mention'
    if item['tipo'] == '1:1':
        return '1:1'
    return 'grupo'


def sort_key(item: dict) -> tuple:
    order = {'mention': 0, '1:1': 1, 'grupo': 2}
    return (order.get(categoria(item), 9), -item['ultima_msg_ms'])


def parse_result(raw: str) -> list:
    s = raw.find('### Result')
    e = raw.find('### Ran Playwright code')
    if s < 0:
        print('nenhum resultado na saída do playwright-cli', file=sys.stderr)
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

    # Atualiza banco silenciosamente
    conn = contacts_db.open_db()
    if conn:
        novos = 0
        for item in data:
            is_new = contacts_db.upsert(
                conn, item['id'], item['tipo'], item['nome'],
                item['ultima_msg_ms'], item['unread'], item['mentions']
            )
            if is_new:
                novos += 1
        if novos:
            print(f'# {novos} novo(s) adicionado(s) ao contacts.db', file=sys.stderr)
        conn.close()

    data.sort(key=sort_key)

    for item in data:
        cat   = categoria(item)
        title = ' '.join(str(item['nome']).split()) or item['id']
        print(f"{cat}\t{item['unread']}\t{item['mentions']}\t{item['id']}\t{title}")


if __name__ == '__main__':
    main()
