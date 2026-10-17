#!/usr/bin/env python3
"""
Conecta o playwright-cli ao Chrome do usuário via CDP e seleciona a aba do Teams.

Delega ao tools/attach.sh do browser-automation-skill (base CDP genérica).
Fallback: implementação própria se o attach.sh não estiver disponível.

Uso: python3 attach.py [-s <nome_sessao>]
Saída: "ok <titulo da aba>" ou erro + exit 1
"""

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import session as _session_helper

DEVTOOLS_FILE = Path.home() / '.config/google-chrome/DevToolsActivePort'

# Localiza o attach.sh do browser-automation-skill (instalado como skill do Kiro Crew)
ATTACH_SH_CANDIDATES = [
    Path.home() / '.kiro/crew/skills/browser-automation/tools/attach.sh',
    Path.home() / '.kiro/skills/browser-automation/tools/attach.sh',
]


def find_attach_sh() -> Path | None:
    for p in ATTACH_SH_CANDIDATES:
        if p.exists():
            return p
    return None


def attach_via_sh(session: str | None) -> int:
    attach_sh = find_attach_sh()
    if not attach_sh:
        return -1  # sinal para usar fallback
    cmd = ['bash', str(attach_sh)]
    if session:
        cmd += ['-s', session]
    r = subprocess.run(cmd)
    return r.returncode


def attach_fallback(session: str | None) -> int:
    """Implementação própria, caso o attach.sh do browser-automation não esteja disponível."""
    if not DEVTOOLS_FILE.exists() or DEVTOOLS_FILE.stat().st_size == 0:
        print('erro: Chrome sem remote debugging (DevToolsActivePort ausente)', file=sys.stderr)
        print('Abra o Chrome e habilite em chrome://inspect/#remote-debugging', file=sys.stderr)
        return 1

    lines = DEVTOOLS_FILE.read_text().splitlines()
    if len(lines) < 2:
        print('erro: DevToolsActivePort com formato inesperado', file=sys.stderr)
        return 1

    port, wspath = lines[0].strip(), lines[1].strip()
    if not re.match(r'^\d+$', port) or not re.match(r'^/devtools/browser/[A-Za-z0-9-]+$', wspath):
        print('erro: DevToolsActivePort com formato inesperado', file=sys.stderr)
        return 1

    cdp_url = f'ws://127.0.0.1:{port}{wspath}'
    sess_args = [f'-s={session}'] if session else []

    # Verifica se já conectado
    r = subprocess.run(['playwright-cli'] + sess_args + ['tab-list'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # Tenta conectar
        r2 = subprocess.run(['playwright-cli'] + sess_args + ['attach', f'--cdp={cdp_url}'],
                            capture_output=True, text=True)
        if r2.returncode != 0:
            print(f'erro: falha ao conectar no Chrome (porta {port})', file=sys.stderr)
            return 1

    # Seleciona aba do Teams
    tab_list = subprocess.run(['playwright-cli'] + sess_args + ['tab-list'],
                              capture_output=True, text=True)
    teams_line = next(
        (l for l in tab_list.stdout.splitlines() if 'teams.cloud.microsoft' in l),
        None
    )
    if not teams_line:
        print('erro: nenhuma aba do Teams aberta no Chrome', file=sys.stderr)
        return 1

    m = re.match(r'^- (\d+):', teams_line)
    if not m:
        print('erro: formato inesperado na listagem de abas', file=sys.stderr)
        return 1

    idx = m.group(1)
    subprocess.run(['playwright-cli'] + sess_args + ['tab-select', idx],
                   capture_output=True)

    # Confirma
    tab_list2 = subprocess.run(['playwright-cli'] + sess_args + ['tab-list'],
                               capture_output=True, text=True)
    current = next(
        (l for l in tab_list2.stdout.splitlines() if '(current)' in l),
        '(aba selecionada)'
    )
    print(f'ok {current.replace("(current)", "").strip()[:80]}')
    if session:
        _session_helper.save_session(session)
    return 0


def main():
    session = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ('-s', '--session') and i + 1 < len(args):
            session = args[i + 1]
            i += 2
        elif args[i].startswith('-s='):
            session = args[i][3:]
            i += 1
        else:
            i += 1

    # Tenta via attach.sh do browser-automation-skill
    rc = attach_via_sh(session)
    if rc == -1:
        # Fallback próprio
        sys.exit(attach_fallback(session))
    else:
        sys.exit(rc)


if __name__ == '__main__':
    main()
