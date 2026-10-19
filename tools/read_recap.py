#!/usr/bin/env python3
"""
Lê o painel de Recapitulação de uma reunião no Teams (anotações de IA + tarefas).

O painel "Recapitular" só está disponível em chats de reunião que tiveram
gravação ou transcrição habilitadas no Teams.

Uso:
  python3 read_recap.py <conversationId> <saida.txt>

Argumento:
  conversationId  ID do chat da reunião (19:...)
  saida.txt       Arquivo de saída (criado/sobrescrito)

Saída: texto plano com seções "## Anotações" e "## Tarefas"
Primeira linha: # fonte: recap | recap-erro | sem-recap

Pré-requisito:
  - Chrome com o chat da reunião aberto numa aba
  - Sessão playwright ativa (rode tools/attach.py antes)
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from session import cli as playwright_cli, get_session_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_js(js: str, timeout: int = 20) -> str:
    return playwright_cli(["run-code", js], timeout=timeout)


def parse_result(raw: str):
    s = raw.find("### Result")
    if s < 0:
        return None
    end = raw.find("### Ran Playwright code", s)
    body = raw[s + len("### Result"):end].strip() if end >= 0 else raw[s + len("### Result"):].strip()
    # Remove aspas externas se for string JSON simples
    import json
    try:
        return json.loads(body)
    except Exception:
        return body.strip('"').replace('\\"', '"') if body.startswith('"') else body


def find_tab_with_conv(conv_id: str) -> int | None:
    """Retorna o índice da aba que tem o chat aberto, ou None."""
    raw = playwright_cli(["tab-list"])
    for line in raw.splitlines():
        m = re.match(r"^\s*-\s*(\d+):", line)
        if m and conv_id[:20] in line:
            return int(m.group(1))
    return None


def navigate_to_chat(conv_id: str) -> bool:
    """
    Garante que o chat está aberto numa aba e seleciona ela.
    Retorna True se bem-sucedido.
    """
    idx = find_tab_with_conv(conv_id)
    if idx is not None:
        playwright_cli(["tab-select", str(idx)])
        return True

    # Abrir via deep link numa aba nova a partir de aba do Teams existente
    dl = f"https://teams.cloud.microsoft/l/chat/{conv_id}/conversations"
    raw = playwright_cli(["tab-list"])
    teams_idx = None
    for line in raw.splitlines():
        m = re.match(r"^\s*-\s*(\d+):", line)
        if m and "teams.cloud.microsoft" in line:
            teams_idx = int(m.group(1))
            break

    if teams_idx is None:
        return False

    playwright_cli(["tab-select", str(teams_idx)])
    run_js(f"async (page) => {{ await page.evaluate(u => window.open(u, '_blank'), {repr(dl)}); }}")

    import time
    time.sleep(4)

    # Selecionar a nova aba
    raw2 = playwright_cli(["tab-list"])
    for line in raw2.splitlines():
        m = re.match(r"^\s*-\s*(\d+):", line)
        if m and ("teams.cloud.microsoft/v2" in line or "Problemas" in line or conv_id[:15] in line):
            playwright_cli(["tab-select", m.group(1)])
            time.sleep(3)
            return True

    return False


def click_recap_tab() -> bool:
    """Clica na aba 'Recapitular' do chat. Retorna True se encontrou."""
    JS = """
async (page) => {
  return await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button'))
      .find(b => b.getAttribute('data-tid') === 'tab-item-com.microsoft.chattabs.recap'
             || b.innerText.trim() === 'Recapitular');
    if (!btn) return false;
    btn.click();
    return true;
  });
}
"""
    raw = run_js(JS)
    result = parse_result(raw)
    return result is True


def extract_recap_text() -> dict | None:
    """
    Extrai anotações de IA e tarefas do painel de recapitulação.
    Aguarda até 8s para o conteúdo carregar.
    """
    import time

    JS = """
async (page) => {
  return await page.evaluate(() => {
    // O painel de recap carrega dentro do body — buscar pelo conteúdo
    const body = document.body.innerText;

    // Marcadores conhecidos do recap
    const notesStart = body.indexOf('Anotações da reunião');
    const tasksStart = body.indexOf('Tarefas de acompanhamento');

    if (notesStart < 0 && tasksStart < 0) return null;

    let notes = '';
    let tasks = '';

    if (notesStart >= 0) {
      const end = tasksStart >= 0 ? tasksStart : notesStart + 6000;
      notes = body.substring(notesStart + 'Anotações da reunião'.length, end).trim();
      // Remove "Expandir todos" e "Estas anotações são úteis?" etc.
      notes = notes.replace(/^Expandir todos\\n?/, '').trim();
    }

    if (tasksStart >= 0) {
      tasks = body.substring(tasksStart + 'Tarefas de acompanhamento'.length, tasksStart + 8000).trim();
      // Remove trailing noise
      const noiseIdx = tasks.indexOf('Estas tarefas são úteis?');
      if (noiseIdx >= 0) tasks = tasks.substring(0, noiseIdx).trim();
    }

    return { notes, tasks };
  });
}
"""
    for attempt in range(3):
        raw = run_js(JS, timeout=25)
        result = parse_result(raw)
        if result and isinstance(result, dict) and (result.get("notes") or result.get("tasks")):
            return result
        time.sleep(3)

    return None


# ---------------------------------------------------------------------------
# Formatação de saída
# ---------------------------------------------------------------------------

def format_output(data: dict) -> list[str]:
    lines = ["# fonte: recap"]

    notes = (data.get("notes") or "").strip()
    tasks = (data.get("tasks") or "").strip()

    if notes:
        lines.append("")
        lines.append("## Anotações da reunião (IA)")
        lines.append("")
        for paragraph in notes.split("\n\n"):
            paragraph = paragraph.strip()
            if paragraph:
                lines.append(paragraph)
                lines.append("")

    if tasks:
        lines.append("")
        lines.append("## Tarefas de acompanhamento")
        lines.append("")
        # Cada task começa com ".\n" no Teams — separar por isso
        task_items = re.split(r"\n\.\n", "\n" + tasks)
        for item in task_items:
            item = item.strip()
            if item:
                # Extrair responsável entre parênteses no final
                lines.append(f"- {item}")
                lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Uso: read_recap.py <conversationId> <saida.txt>", file=sys.stderr)
        sys.exit(1)

    conv_id = sys.argv[1]
    saida = Path(sys.argv[2])

    if not re.match(r"^19:", conv_id):
        print(f"conversationId inválido (deve começar com '19:'): {conv_id}", file=sys.stderr)
        sys.exit(1)

    saida.parent.mkdir(parents=True, exist_ok=True)

    # Verificar sessão
    session = get_session_name(strict=False)
    if not session:
        saida.write_text("# fonte: recap-erro — sem sessão playwright com Teams\n", encoding="utf-8")
        print("Erro: nenhuma sessão playwright com o Teams. Rode: python3 tools/attach.py", file=sys.stderr)
        sys.exit(1)

    # Garantir que o chat está aberto
    if not navigate_to_chat(conv_id):
        saida.write_text("# fonte: recap-erro — não foi possível abrir o chat no Teams\n", encoding="utf-8")
        print("Erro: não foi possível abrir o chat no Teams.", file=sys.stderr)
        sys.exit(1)

    # Clicar na aba Recapitular
    found = click_recap_tab()
    if not found:
        saida.write_text("# fonte: sem-recap — aba Recapitular não encontrada (reunião sem transcrição?)\n", encoding="utf-8")
        print("Info: aba Recapitular não encontrada. Chat pode não ser de reunião ou sem transcrição.", file=sys.stderr)
        sys.exit(0)

    # Extrair conteúdo
    import time
    time.sleep(2)  # aguardar painel carregar
    data = extract_recap_text()

    if not data:
        saida.write_text("# fonte: recap-erro — painel carregou mas sem conteúdo extraível\n", encoding="utf-8")
        print("Aviso: painel de recapitulação sem conteúdo extraível.", file=sys.stderr)
        sys.exit(0)

    lines = format_output(data)
    saida.write_text("\n".join(lines) + "\n", encoding="utf-8")

    notes_count = sum(1 for l in lines if l and not l.startswith("#") and not l.startswith("##"))
    tasks_count = lines.count("## Tarefas de acompanhamento")
    print(f"Recapitulação gravada em {saida} ({notes_count} linhas, tarefas: {tasks_count > 0})")


if __name__ == "__main__":
    main()
