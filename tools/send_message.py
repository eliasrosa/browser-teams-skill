#!/usr/bin/env python3
"""
Envia uma mensagem para um chat do Teams via busca global (Ctrl+K).

Fluxo:
  1. Garante que a aba do Teams está ativa (tab-select pela URL)
  2. Abre a busca global com Ctrl+K
  3. Digita o nome do destinatário e seleciona o chat
  4. Digita a mensagem com o prefixo configurado
  5. Envia com o atalho configurado (send_key)

Uso:
  python3 send_message.py <nome_ou_id> <mensagem>

  <nome_ou_id>: nome como aparece no Teams (ex: "José Vinícius") ou conversationId (19:...)
                Quando é um ID, o nome é resolvido pelo contacts.db

Exemplos:
  python3 send_message.py "José Vinícius" "Boa, aprovei a PR!"
  python3 send_message.py "Squad GW Daily" "Daily cancelada hoje"

Pré-requisito: attach.py já conectado (playwright-cli com sessão ativa).
"""

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db as contacts_db
from config import get_config

TEAMS_URL = "teams.cloud.microsoft"


def run(cmd: list[str], timeout: int = 10) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout


def get_tab_list() -> list[dict]:
    """Retorna lista de abas abertas: [{index, title, url, current}]"""
    out = run(["playwright-cli", "tab-list"])
    tabs = []
    for line in out.split("\n"):
        line = line.strip()
        if not line.startswith("- "):
            continue
        current = "(current)" in line
        # formato: "- N: (current) [Título](URL)" ou "- N: [Título](URL)"
        import re
        m = re.match(r"- (\d+):.*\[([^\]]*)\]\(([^)]+)\)", line)
        if m:
            tabs.append({
                "index": int(m.group(1)),
                "title": m.group(2),
                "url": m.group(3),
                "current": current,
            })
    return tabs


def select_teams_tab() -> bool:
    """Garante que a aba ativa é uma aba do Teams. Retorna True se OK."""
    tabs = get_tab_list()
    teams_tabs = [t for t in tabs if TEAMS_URL in t["url"]]
    if not teams_tabs:
        print("Erro: nenhuma aba do Teams encontrada. Abra o Teams no Chrome.", file=sys.stderr)
        return False

    # Preferir a que já é current se for Teams
    current = next((t for t in teams_tabs if t["current"]), None)
    if current:
        return True  # já está na aba certa

    # Selecionar a primeira aba do Teams
    best = teams_tabs[0]
    run(["playwright-cli", "tab-select", str(best["index"])])
    time.sleep(1)
    return True


def resolve_name(name_or_id: str) -> str:
    """Se for conversationId (19:...), resolve para nome via contacts.db."""
    if not name_or_id.startswith("19:"):
        return name_or_id
    conn = contacts_db.open_db()
    if not conn:
        return name_or_id
    row = conn.execute(
        "SELECT nome FROM contacts WHERE id = ?", (name_or_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else name_or_id


def validate_recipient(name_or_id: str) -> tuple[str, str] | None:
    """
    Valida o destinatário contra o contacts.db antes de enviar.

    Retorna (nome, conversation_id) se validado com segurança.
    Retorna None se ambíguo ou não encontrado (imprime motivo).

    Casos:
      - conversationId direto (19:...)  → resolve nome, sem ambiguidade
      - nome com match único no DB      → confirma ID, prossegue
      - nome com múltiplos matches      → lista e interrompe (ambíguo)
      - nome sem match no DB            → avisa mas prossegue (não tem ID)
    """
    conn = contacts_db.open_db()

    # Caso 1: já é um ID
    if name_or_id.startswith("19:"):
        if not conn:
            return (name_or_id, name_or_id)
        row = conn.execute(
            "SELECT nome, id FROM contacts WHERE id = ?", (name_or_id,)
        ).fetchone()
        conn.close()
        if row:
            print(f"✓ Destinatário validado: {row[0]} (id: {row[1][:40]}...)")
            return (row[0], row[1])
        print(f"Aviso: ID não encontrado no contacts.db — pode estar desatualizado.", file=sys.stderr)
        return (name_or_id, name_or_id)

    # Caso 2: busca por nome (LIKE, case-insensitive)
    if conn:
        rows = conn.execute(
            "SELECT nome, id, tipo FROM contacts WHERE nome LIKE ? COLLATE NOCASE",
            (f"%{name_or_id}%",)
        ).fetchall()
        conn.close()

        if len(rows) == 1:
            nome, conv_id, tipo = rows[0]
            print(f"✓ Destinatário validado: {nome} [{tipo}] (id: {conv_id[:40]}...)")
            return (nome, conv_id)

        if len(rows) > 1:
            print(f"\n⚠️  Nome '{name_or_id}' é ambíguo — {len(rows)} matches no contacts.db:", file=sys.stderr)
            for i, (nome, conv_id, tipo) in enumerate(rows, 1):
                print(f"  {i}. {nome} [{tipo}]  id: {conv_id[:50]}", file=sys.stderr)
            print("\nUse o conversationId diretamente para evitar envio errado.", file=sys.stderr)
            print("Exemplo: python3 send_message.py '19:abc...' 'mensagem'", file=sys.stderr)
            return None

        # Nenhum match no DB
        print(f"Aviso: '{name_or_id}' não encontrado no contacts.db. Tentando pela busca do Teams.", file=sys.stderr)
        print("Se o nome for ambíguo no Teams, o chat errado pode ser aberto.", file=sys.stderr)

    return (name_or_id, name_or_id)  # prossegue sem ID confirmado


def send(name_or_id: str, message: str) -> bool:
    """
    Envia mensagem para o destinatário no Teams.
    Valida ambiguidade via contacts.db antes de qualquer ação no browser.
    Retorna True se enviado com sucesso.
    """
    cfg = get_config()
    prefix = cfg.get("message_prefix", "🤖 ")
    send_key = cfg.get("send_key", "Ctrl+Enter")
    full_message = prefix + message

    # 1. Validar destinatário antes de tocar no browser
    result = validate_recipient(name_or_id)
    if result is None:
        return False  # ambíguo — interrompe sem abrir nada
    nome, conv_id = result

    print(f"Enviando para: {nome}")

    # 2. Garantir aba do Teams ativa
    if not select_teams_tab():
        return False
    run(["playwright-cli", "press-key", "Control+k"])
    time.sleep(1.2)

    # 3. Snapshot para confirmar que a busca abriu
    snap = run(["playwright-cli", "snapshot"])
    if "search" not in snap.lower() and "busca" not in snap.lower() and "Search" not in snap:
        # Tentar Ctrl+F como fallback
        run(["playwright-cli", "press-key", "Escape"])
        time.sleep(0.5)
        run(["playwright-cli", "press-key", "Control+k"])
        time.sleep(1.2)

    # 4. Digitar o nome para buscar
    run(["playwright-cli", "type", nome])
    time.sleep(1.5)

    # 5. Pressionar Enter para abrir o primeiro resultado
    run(["playwright-cli", "press-key", "ArrowDown"])
    time.sleep(0.5)
    run(["playwright-cli", "press-key", "Enter"])
    time.sleep(2)

    # 6. Verificar se o editor de mensagem está disponível
    snap = run(["playwright-cli", "snapshot"])
    if "Type a message" not in snap and "textbox" not in snap.lower():
        # Tentar Escape e re-buscar
        print("Editor não encontrado após busca. Tentando novamente...", file=sys.stderr)
        run(["playwright-cli", "press-key", "Escape"])
        time.sleep(0.5)
        run(["playwright-cli", "press-key", "Control+k"])
        time.sleep(1.2)
        run(["playwright-cli", "type", nome])
        time.sleep(1.5)
        run(["playwright-cli", "press-key", "ArrowDown"])
        time.sleep(0.5)
        run(["playwright-cli", "press-key", "Enter"])
        time.sleep(2.5)
        snap = run(["playwright-cli", "snapshot"])
        if "Type a message" not in snap:
            print(f"Erro: não foi possível abrir o chat de '{nome}'.", file=sys.stderr)
            return False

    # 7. Clicar no editor e digitar a mensagem
    import re
    m = re.search(r'textbox "Type a message".*\[ref=(\w+)\]', snap)
    if m:
        run(["playwright-cli", "click", m.group(1)])
        time.sleep(0.3)

    run(["playwright-cli", "type", full_message])
    time.sleep(0.5)

    # 8. Verificar o texto digitado antes de enviar
    snap2 = run(["playwright-cli", "snapshot"])
    if message[:20] not in snap2:
        print("Aviso: texto pode não ter sido digitado corretamente.", file=sys.stderr)

    # 9. Enviar
    run(["playwright-cli", "press-key", send_key])
    time.sleep(1.5)

    # 10. Confirmar que o editor ficou vazio (enviado)
    snap3 = run(["playwright-cli", "snapshot"])
    m2 = re.search(r'textbox "Type a message".*\[ref=(\w+)\]', snap3)
    if m2:
        # Verificar se o editor está vazio
        empty = re.search(r'textbox "Type a message"[^\n]*\n\s*-', snap3)
        if not empty:
            # Checar se o texto da mensagem desapareceu do editor
            if message[:20] in snap3:
                print("Aviso: editor ainda tem texto — mensagem pode não ter sido enviada.", file=sys.stderr)
                return False

    print(f"✓ Mensagem enviada para '{nome}'.")
    return True


def main():
    if len(sys.argv) < 3:
        print("Uso: python3 send_message.py <nome_ou_id> <mensagem>", file=sys.stderr)
        sys.exit(1)

    name_or_id = sys.argv[1]
    message = " ".join(sys.argv[2:])

    ok = send(name_or_id, message)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
