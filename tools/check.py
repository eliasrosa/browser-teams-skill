#!/usr/bin/env python3
"""
Pré-check: valida que todos os requisitos da browser-teams-skill estão satisfeitos.

Uso: python3 tools/check.py
Saída: lista de ✓/✗ por requisito; exit 1 se algum falhar.
"""
import shutil
import subprocess
import sys
from pathlib import Path

DATA = Path(__file__).parent.parent / ".data"
SKILL_DIR = Path(__file__).parent.parent

ok = True


def check(label: str, result: bool, fix: str = "") -> None:
    global ok
    status = "✓" if result else "✗"
    print(f"  {status} {label}")
    if not result:
        if fix:
            print(f"    → {fix}")
        ok = False


print("Verificando requisitos da browser-teams-skill...\n")

# --- Ferramentas externas ---
print("Ferramentas:")

check(
    "playwright-cli instalado",
    shutil.which("playwright-cli") is not None,
    "npm install -g @playwright/cli@latest  (requer Node.js 20+)",
)

check(
    "Python 3.10+",
    sys.version_info >= (3, 10),
    f"versão atual: {sys.version.split()[0]} — instalar Python 3.10+",
)

# --- browser-automation-skill (dependência base) ---
print("\nDependências:")

ba_candidates = [
    Path.home() / ".kiro/crew/skills/browser-automation/tools/attach.sh",
    Path.home() / ".kiro/skills/browser-automation/tools/attach.sh",
]
has_ba = any(p.exists() for p in ba_candidates)
check(
    "browser-automation-skill instalada",
    has_ba,
    "git clone https://github.com/eliasrosa/browser-automation-skill ~/.kiro/crew/skills/browser-automation",
)

# --- Dados locais (.data/) ---
print("\nEstado local (.data/):")

check(
    ".data/config.json existe",
    (DATA / "config.json").exists(),
    "python3 tools/config.py  # cria com defaults",
)

check(
    ".data/contacts.db populado",
    (DATA / "contacts.db").exists(),
    "python3 tools/attach.py && python3 tools/map_contacts.py  # onboarding inicial",
)

session_file = DATA / "session_name"
check(
    ".data/session_name existe",
    session_file.exists(),
    "python3 tools/attach.py  # conecta e persiste a sessão",
)

# --- Conectividade ---
print("\nConectividade:")

devtools = Path.home() / ".config/google-chrome/DevToolsActivePort"
check(
    "Chrome com remote debugging ativo (DevToolsActivePort)",
    devtools.exists() and devtools.stat().st_size > 0,
    "Abra o Chrome → chrome://inspect/#remote-debugging → habilite remote debugging",
)

# Verificar sessão playwright ativa (só se o arquivo de sessão existe)
if session_file.exists():
    session_name = session_file.read_text().strip()
    try:
        r = subprocess.run(
            ["playwright-cli", f"-s={session_name}", "tab-list"],
            capture_output=True, text=True, timeout=5,
        )
        has_teams = "teams.cloud.microsoft" in r.stdout
        check(
            f"Sessão playwright '{session_name}' tem aba do Teams",
            has_teams,
            "Abra o Teams no Chrome e rode: python3 tools/attach.py",
        )
    except Exception:
        check(
            "Sessão playwright acessível",
            False,
            "python3 tools/attach.py",
        )
else:
    check(
        "Sessão playwright configurada",
        False,
        "python3 tools/attach.py",
    )

# --- Resultado final ---
print()
if ok:
    print("✓ Todos os requisitos satisfeitos. A skill está pronta para uso.")
else:
    print("✗ Corrija os itens marcados com ✗ antes de usar a skill.")
    sys.exit(1)
