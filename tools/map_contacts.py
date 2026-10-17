#!/usr/bin/env python3
"""
Mapeia todos os chats do Teams para um banco SQLite local em .data/contacts.db.

Lê o IndexedDB 'Teams:conversation-manager' pelo Chrome via playwright-cli e grava
cada chat (ID, nome, tipo, última mensagem). Rodadas seguintes fazem INSERT OR REPLACE,
preservando dados que o Teams não retornar mais (chats arquivados).

Uso:
  python3 map_contacts.py [--skill-dir <path>] [--dry-run]

  --skill-dir   Caminho para a pasta da skill (default: pasta pai deste script)
  --dry-run     Imprime o que seria gravado, sem tocar o banco

Saída: resumo de novos/atualizados + caminho do banco

Pré-requisito: playwright-cli conectado com a aba do Teams como "current" (attach.py).
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BRT = timezone(timedelta(hours=-3))

# ---------------------------------------------------------------------------
# Banco SQLite
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS contacts (
    id            TEXT PRIMARY KEY,
    tipo          TEXT NOT NULL,
    nome          TEXT NOT NULL,
    ultima_msg_ms INTEGER DEFAULT 0,
    unread        INTEGER DEFAULT 0,
    mentions      INTEGER DEFAULT 0,
    atualizado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tipo      ON contacts(tipo);
CREATE INDEX IF NOT EXISTS idx_ultima_msg ON contacts(ultima_msg_ms DESC);
"""

def open_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.commit()
    return conn


def upsert_contacts(conn: sqlite3.Connection, rows: list[dict], now: str) -> tuple[int, int]:
    """Retorna (novos, atualizados)."""
    novos = atualizados = 0
    for r in rows:
        existing = conn.execute(
            'SELECT id FROM contacts WHERE id = ?', (r['id'],)
        ).fetchone()
        conn.execute(
            """INSERT INTO contacts (id, tipo, nome, ultima_msg_ms, unread, mentions, atualizado_em)
               VALUES (:id, :tipo, :nome, :ultima_msg_ms, :unread, :mentions, :atualizado_em)
               ON CONFLICT(id) DO UPDATE SET
                 tipo          = excluded.tipo,
                 nome          = excluded.nome,
                 ultima_msg_ms = excluded.ultima_msg_ms,
                 unread        = excluded.unread,
                 mentions      = excluded.mentions,
                 atualizado_em = excluded.atualizado_em""",
            {**r, 'atualizado_em': now}
        )
        if existing:
            atualizados += 1
        else:
            novos += 1
    conn.commit()
    return novos, atualizados


# ---------------------------------------------------------------------------
# Leitura do IndexedDB via playwright-cli
# ---------------------------------------------------------------------------

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
      .map(c => {
        const ct = c.chatTitle;
        const nome = (ct && typeof ct === 'object')
          ? (ct.shortTitle || ct.displayName || '')
          : (ct || (c.threadProperties || {}).topic || '');
        // tipo inferido pelo padrão do ID (campos chatType/threadType vêm vazios no IndexedDB)
        const id = String(c.id || '');
        const tipo = id.includes('@unq.gbl.spaces') ? '1:1'
                   : id.includes('meeting_')         ? 'meeting'
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

def fetch_from_teams() -> list[dict]:
    r = subprocess.run(
        ['playwright-cli', 'run-code', JS],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f'playwright-cli falhou:\n{r.stderr}', file=sys.stderr)
        sys.exit(1)

    raw = r.stdout
    s = raw.find('### Result')
    e = raw.find('### Ran Playwright code')
    if s < 0:
        print('nenhum resultado na saída do playwright-cli', file=sys.stderr)
        sys.exit(1)
    body = raw[s + len('### Result'):e].strip() if e >= 0 else raw[s + len('### Result'):].strip()

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        print(f'erro ao parsear JSON: {exc}\ntrecho: {body[:300]}', file=sys.stderr)
        sys.exit(1)

    if isinstance(data, dict) and 'erro' in data:
        print(f'Teams IndexedDB: {data["erro"]}', file=sys.stderr)
        sys.exit(1)

    return data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def resolve_skill_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    # pasta pai do próprio script → raiz da skill
    return Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description='Mapeia chats do Teams para .data/contacts.db')
    ap.add_argument('--skill-dir', default=None, help='Caminho para a pasta da skill')
    ap.add_argument('--dry-run', action='store_true', help='Imprime sem gravar')
    args = ap.parse_args()

    skill_dir = resolve_skill_dir(args.skill_dir)
    db_path   = skill_dir / '.data' / 'contacts.db'

    print(f'Lendo IndexedDB do Teams...')
    rows = fetch_from_teams()
    now  = datetime.now(BRT).strftime('%Y-%m-%d %H:%M')

    if args.dry_run:
        print(f'\n{len(rows)} chats encontrados (dry-run — nada gravado):\n')
        for r in sorted(rows, key=lambda x: (-x['ultima_msg_ms'])):
            ts = datetime.fromtimestamp(r['ultima_msg_ms'] / 1000, BRT).strftime('%d/%m %H:%M') if r['ultima_msg_ms'] else '—'
            unread = f" [{r['unread']} nãolido]" if r['unread'] else ''
            mention = f" [@{r['mentions']}]" if r['mentions'] else ''
            print(f"  {r['tipo']:8}  {ts}  {r['nome'][:50]}{unread}{mention}")
        return

    conn  = open_db(db_path)
    novos, atualizados = upsert_contacts(conn, rows, now)
    total = conn.execute('SELECT COUNT(*) FROM contacts').fetchone()[0]
    conn.close()

    print(f'✓ {db_path}')
    print(f'  {novos} novos  |  {atualizados} atualizados  |  {total} total no banco')

    # Resumo por tipo
    conn2 = sqlite3.connect(db_path)
    for tipo, count in conn2.execute(
        'SELECT tipo, COUNT(*) FROM contacts GROUP BY tipo ORDER BY tipo'
    ).fetchall():
        print(f'  {tipo}: {count}')
    conn2.close()


if __name__ == '__main__':
    main()
