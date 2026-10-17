"""
Helper compartilhado: leitura e atualização incremental de .data/contacts.db.

Usado por list_unread.py, list_changed.py e read_chat.py para:
  - resolver nome de um conversationId
  - atualizar o banco silenciosamente quando encontrar chat novo ou atualizado
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

BRT = timezone(timedelta(hours=-3))

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
CREATE INDEX IF NOT EXISTS idx_tipo       ON contacts(tipo);
CREATE INDEX IF NOT EXISTS idx_ultima_msg ON contacts(ultima_msg_ms DESC);
"""


def _db_path(skill_dir: Path | None = None) -> Path:
    if skill_dir:
        return Path(skill_dir) / '.data' / 'contacts.db'
    # localiza a raiz da skill: tools/ está um nível abaixo
    return Path(__file__).resolve().parent.parent / '.data' / 'contacts.db'


def open_db(skill_dir: Path | None = None) -> sqlite3.Connection | None:
    """
    Abre o banco se existir. Cria tabelas se necessário.
    Retorna None se o banco não existir (usuário ainda não rodou map_contacts.py).
    """
    path = _db_path(skill_dir)
    if not path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.commit()
    return conn


def resolve_name(conv_id: str, conn: sqlite3.Connection | None) -> str:
    """Retorna o nome do chat ou o próprio ID se não mapeado."""
    if not conn:
        return conv_id
    row = conn.execute('SELECT nome FROM contacts WHERE id = ?', (conv_id,)).fetchone()
    return row['nome'] if row else conv_id


def upsert(conn: sqlite3.Connection, conv_id: str, tipo: str, nome: str,
           ultima_msg_ms: int = 0, unread: int = 0, mentions: int = 0) -> bool:
    """
    Insere ou atualiza um contato. Retorna True se foi novidade (INSERT).
    Só atualiza ultima_msg_ms, unread e mentions se o valor novo for maior/diferente
    para não regredir dados com informação parcial.
    """
    now = datetime.now(BRT).strftime('%Y-%m-%d %H:%M')
    existing = conn.execute('SELECT ultima_msg_ms FROM contacts WHERE id = ?', (conv_id,)).fetchone()

    if existing is None:
        conn.execute(
            """INSERT INTO contacts (id, tipo, nome, ultima_msg_ms, unread, mentions, atualizado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (conv_id, tipo, nome, ultima_msg_ms, unread, mentions, now)
        )
        conn.commit()
        return True  # novo

    # Atualiza nome e campos numéricos se melhorarem
    conn.execute(
        """UPDATE contacts SET
             nome          = ?,
             tipo          = ?,
             ultima_msg_ms = MAX(ultima_msg_ms, ?),
             unread        = ?,
             mentions      = ?,
             atualizado_em = ?
           WHERE id = ?""",
        (nome, tipo, ultima_msg_ms, unread, mentions, now, conv_id)
    )
    conn.commit()
    return False  # atualizado


def all_contacts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        'SELECT id, tipo, nome, ultima_msg_ms, unread, mentions FROM contacts ORDER BY ultima_msg_ms DESC'
    ).fetchall()
    return [dict(r) for r in rows]
