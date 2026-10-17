#!/usr/bin/env python3
"""
Helper: resolve e injeta o nome de sessão do playwright-cli automaticamente.

Problema que resolve:
  playwright-cli sem -s= opera numa sessão diferente da que tem o Teams aberto,
  causando "aba vazia" e ~30 tentativas para fazer o que deveria ser 4 passos.

Como funciona:
  1. Lê .data/session_name (gravado pelo attach.py ou manualmente)
  2. Valida que a sessão tem o Teams aberto (tab-list -s=<nome>)
  3. Se não encontrar, auto-detecta a sessão com o Teams entre as ativas
  4. Expõe `cli(cmd)` que injeta -s=<sessao> automaticamente

Uso nos scripts da skill:
  from session import cli, get_session_name
  cli(["run-code", JS])               # injeta -s= automaticamente
  cli(["press-key", "Ctrl+Enter"])    # mesmo
  nome = get_session_name()           # retorna o nome ou None
"""

import json
import re
import subprocess
from pathlib import Path

# .data fica na raiz da skill (mesmo diretório do tools/, um nível acima)
DATA_DIR = Path(__file__).parent.parent / ".data"
SESSION_FILE = DATA_DIR / "session_name"
TEAMS_URL = "teams.cloud.microsoft"


def _run_raw(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    """Roda playwright-cli sem -s= (usado só para detectar sessões)."""
    r = subprocess.run(
        ["playwright-cli"] + cmd,
        capture_output=True, text=True, timeout=timeout
    )
    return r.returncode, r.stdout


def _list_sessions() -> list[str]:
    """Lista sessões playwright ativas (playwright-cli list)."""
    _, out = _run_raw(["list"])
    sessions = []
    for line in out.splitlines():
        # formato: "- <nome>" ou similar
        m = re.match(r"^\s*[-*]\s+(\S+)", line)
        if m and m.group(1) not in ("No", "Sessions:"):
            sessions.append(m.group(1))
    return sessions


def _session_has_teams(session_name: str) -> bool:
    """Verifica se a sessão tem aba do Teams aberta."""
    _, out = _run_raw(["tab-list", f"-s={session_name}"])
    return TEAMS_URL in out


def _auto_detect() -> str | None:
    """Detecta automaticamente a sessão com o Teams aberto."""
    sessions = _list_sessions()
    for s in sessions:
        if _session_has_teams(s):
            return s
    return None


def get_session_name(strict: bool = False) -> str | None:
    """
    Retorna o nome da sessão playwright com o Teams ativo.

    Ordem de resolução:
      1. .data/session_name (persistido pelo attach.py)
      2. Auto-detecção entre sessões ativas (playwright-cli list)
      3. None se não encontrar (ou RuntimeError se strict=True)
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Arquivo persistido
    if SESSION_FILE.exists():
        saved = SESSION_FILE.read_text().strip()
        if saved and _session_has_teams(saved):
            return saved

    # 2. Auto-detecção
    detected = _auto_detect()
    if detected:
        # Persiste para as próximas chamadas
        SESSION_FILE.write_text(detected)
        return detected

    if strict:
        raise RuntimeError(
            "Nenhuma sessão playwright com o Teams encontrada. "
            "Rode primeiro: python3 tools/attach.py"
        )
    return None


def cli(args: list[str], session: str | None = None, timeout: int = 15) -> str:
    """
    Roda playwright-cli com -s=<sessao> injetado automaticamente.

    Args:
      args:    Argumentos sem 'playwright-cli' e sem '-s=...'
      session: Nome explícito da sessão (ou None para auto-resolver)
      timeout: Timeout em segundos

    Returns:
      stdout do comando

    Raises:
      RuntimeError se não encontrar sessão com o Teams
    """
    s = session or get_session_name(strict=True)
    cmd = ["playwright-cli", f"-s={s}"] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout


def save_session(name: str) -> None:
    """Persiste o nome da sessão (chamado pelo attach.py após conectar)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(name)


def parse_playwright_result(raw: str):
    """Extrai e faz parse do JSON de resultado de um run-code."""
    s = raw.find("### Result")
    e = raw.find("### Ran Playwright code")
    if s < 0:
        return None
    body = raw[s + len("### Result"):e].strip() if e >= 0 else raw[s + len("### Result"):].strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    # Diagnóstico direto: python3 session.py
    name = get_session_name()
    if name:
        print(f"✓ Sessão ativa: {name}")
        _, out = _run_raw(["tab-list", f"-s={name}"])
        teams_tabs = [l for l in out.splitlines() if TEAMS_URL in l]
        print(f"  {len(teams_tabs)} aba(s) do Teams na sessão")
        for t in teams_tabs:
            print(f"  {t.strip()}")
    else:
        print("✗ Nenhuma sessão com o Teams encontrada.")
        print("  Rode: python3 tools/attach.py")
