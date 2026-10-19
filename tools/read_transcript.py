#!/usr/bin/env python3
"""
Lê a transcrição completa de uma reunião no Teams.

A transcrição fica num iframe do SharePoint/OneDrive dentro do painel
"Recapitular > Transcrição". O Teams virtualiza o scroll, então o script
rola iterativamente até o marcador de fim ("parou a transcrição").

Uso:
  python3 read_transcript.py <conversationId> <saida.txt>

Argumento:
  conversationId  ID do chat da reunião (19:...)
  saida.txt       Arquivo de saída (criado/sobrescrito)

Formato de saída: uma entrada por linha
  Autor HH:MM:SS
  texto da fala

Primeira linha: # fonte: transcript | transcript-erro | sem-transcript

Pré-requisito:
  - Chrome com o chat da reunião aberto ou acessível via deep link
  - Sessão playwright ativa (rode tools/attach.py antes)
"""

import re
import sys
import time
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
    import json
    try:
        return json.loads(body)
    except Exception:
        return body.strip('"').replace('\\"', '"') if body.startswith('"') else body


def find_or_open_chat(conv_id: str) -> bool:
    """Garante que o chat está aberto e selecionado. Retorna True se OK."""
    raw = playwright_cli(["tab-list"])

    # Procurar aba já aberta com o chat
    for line in raw.splitlines():
        m = re.match(r"^\s*-\s*(\d+):", line)
        if m and "teams.cloud.microsoft/v2" in line:
            playwright_cli(["tab-select", m.group(1)])
            time.sleep(2)
            return True

    # Abrir via deep link numa aba nova
    dl = f"https://teams.cloud.microsoft/l/chat/{conv_id}/conversations"
    teams_idx = None
    for line in raw.splitlines():
        m = re.match(r"^\s*-\s*(\d+):", line)
        if m and "teams.cloud.microsoft" in line and "v2" not in line:
            teams_idx = int(m.group(1))
            break

    if teams_idx is None:
        return False

    playwright_cli(["tab-select", str(teams_idx)])
    run_js(f"async (page) => {{ await page.evaluate(u => window.open(u, '_blank'), {repr(dl)}); }}")
    time.sleep(5)

    # Selecionar a nova aba do v2
    raw2 = playwright_cli(["tab-list"])
    for line in raw2.splitlines():
        m = re.match(r"^\s*-\s*(\d+):", line)
        if m and "teams.cloud.microsoft/v2" in line:
            playwright_cli(["tab-select", m.group(1)])
            time.sleep(3)
            return True

    return False


def navigate_to_transcript() -> bool:
    """
    Clica em Recapitular → Transcrição.
    Retorna True se o iframe da transcrição ficou disponível.
    """
    JS = """
async (page) => {
  // 1. Clicar em Recapitular
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button'))
      .find(b => b.getAttribute('data-tid') === 'tab-item-com.microsoft.chattabs.recap'
             || b.innerText.trim() === 'Recapitular');
    if (btn) btn.click();
  });
  await page.waitForTimeout(2500);

  // 2. Clicar em Transcrição
  const clicked = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button'))
      .find(b => b.getAttribute('aria-label') === 'Transcrição'
             || b.innerText.trim() === 'Transcrição');
    if (!btn) return false;
    btn.click();
    return true;
  });
  if (!clicked) return false;

  await page.waitForTimeout(3000);
  return true;
}
"""
    raw = run_js(JS, timeout=30)
    result = parse_result(raw)
    return result is True


def get_transcript_frame_index() -> int | None:
    """Retorna o índice do frame com a transcrição (o maior após o principal)."""
    JS = """
async (page) => {
  function allFrames(f) { const r=[f]; for(const c of f.childFrames()) r.push(...allFrames(c)); return r; }
  const frames = allFrames(page.mainFrame());
  const info = await Promise.all(frames.map(async (f, i) => {
    try {
      const len = await f.evaluate(() => document.body.innerText.length).catch(() => -1);
      return { i, len };
    } catch(e) { return { i, len: -1 }; }
  }));
  // O frame da transcrição é o de maior tamanho (exceto o principal)
  const candidates = info.filter(x => x.i > 0 && x.len > 500);
  if (!candidates.length) return -1;
  return candidates.sort((a, b) => b.len - a.len)[0].i;
}
"""
    raw = run_js(JS)
    result = parse_result(raw)
    if result is None or result == -1:
        return None
    return int(result)


def read_transcript_full(frame_idx: int) -> str | None:
    """
    Lê a transcrição completa rolando o iframe até o marcador de fim.
    Retorna o texto completo ou None em caso de falha.
    """
    MAX_SCROLLS = 20
    prev_len = 0
    stale_rounds = 0

    for i in range(MAX_SCROLLS):
        JS = f"""
async (page) => {{
  function allFrames(f) {{ const r=[f]; for(const c of f.childFrames()) r.push(...allFrames(c)); return r; }}
  const frame = allFrames(page.mainFrame())[{frame_idx}];
  if (!frame) return null;

  // Rolar para o final
  const scrolled = await frame.evaluate(() => {{
    const el = Array.from(document.querySelectorAll('*')).find(e => {{
      const s = getComputedStyle(e);
      return (s.overflowY === 'auto' || s.overflowY === 'scroll')
        && e.scrollHeight > e.clientHeight + 10;
    }});
    if (el) {{ el.scrollTop = el.scrollHeight; return el.scrollHeight; }}
    window.scrollTo(0, document.body.scrollHeight);
    return document.body.scrollHeight;
  }});

  await page.waitForTimeout(1500);

  const text = await frame.evaluate(() => document.body.innerText);
  const done = text.includes('parou a transcrição') || text.includes('stopped transcription');
  return {{ len: text.length, done, text }};
}}
"""
        raw = run_js(JS, timeout=30)
        result = parse_result(raw)

        if not result or not isinstance(result, dict):
            return None

        cur_len = result.get("len", 0)
        done = result.get("done", False)
        text = result.get("text", "")

        if done:
            return text

        # Verificar estagnação
        if cur_len <= prev_len:
            stale_rounds += 1
            if stale_rounds >= 3:
                # Chegamos no fim sem marcador — retornar o que temos
                return text
        else:
            stale_rounds = 0

        prev_len = cur_len

    # Máximo de scrolls atingido — retornar o que temos
    return None


# ---------------------------------------------------------------------------
# Parser do texto bruto → linhas limpas
# ---------------------------------------------------------------------------

def parse_transcript_text(raw: str) -> list[str]:
    """
    Converte o innerText bruto do painel de transcrição em linhas formatadas.

    Formato de entrada (repetido por fala):
      Nome do Participante
      N minutos M segundos
      H:MM:SS
      Nome do Participante H minutos M segundos
      Texto da fala

    Saída:
      Nome (H:MM:SS)
      Texto

    Ignora ruído: "Baixar", "Excluir", "O conteúdo gerado por IA pode estar incorreto",
    "Transcrição. Use as setas...", "começou a transcrição", "parou a transcrição"
    """
    NOISE = {
        "Baixar", "Excluir", "Use enter/espaço para obter mais opções.",
        "O conteúdo gerado por IA pode estar incorreto",
        "Transcrição. Use as setas para navegar entre as entradas da transcrição.",
    }
    TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
    WRITTEN_TIME_RE = re.compile(r"^\d+ minuto[s]? \d+ segundo[s]?$")
    SPEAKER_TIME_RE = re.compile(r"^.+ \d+ minuto[s]? \d+ segundo[s]?$")

    lines = [l.strip() for l in raw.splitlines()]
    entries = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Pular ruído e linhas vazias
        if not line or line in NOISE or TIME_RE.match(line) or WRITTEN_TIME_RE.match(line) or SPEAKER_TIME_RE.match(line):
            i += 1
            continue

        # Marcadores especiais de início/fim
        if "começou a transcrição" in line or "started transcription" in line:
            name = line.split(" começou")[0].split(" started")[0].strip()
            entries.append(f"--- {name} iniciou a transcrição ---")
            i += 1
            continue
        if "parou a transcrição" in line or "stopped transcription" in line:
            name = line.split(" parou")[0].split(" stopped")[0].strip()
            entries.append(f"--- {name} encerrou a transcrição ---")
            i += 1
            continue

        # Coletar falas: linha é texto de fala se as linhas anteriores
        # foram nome + tempo (já consumidos como ruído)
        # Estratégia: agrupar linhas de texto até encontrar próximo padrão
        speech_lines = []
        while i < len(lines):
            l = lines[i]
            if not l or l in NOISE or TIME_RE.match(l) or WRITTEN_TIME_RE.match(l) or SPEAKER_TIME_RE.match(l):
                break
            if "começou a transcrição" in l or "parou a transcrição" in l:
                break
            speech_lines.append(l)
            i += 1

        if speech_lines:
            entries.append(" ".join(speech_lines))
        else:
            i += 1

    return entries


def parse_transcript_structured(raw: str) -> list[dict]:
    """
    Extrai entradas estruturadas: {autor, timestamp_hms, texto}.
    Retorna lista ordenada por timestamp.
    """
    TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
    WRITTEN_TIME_RE = re.compile(r"^(\d+) minuto[s]? (\d+) segundo[s]?$")
    SPEAKER_TIME_RE = re.compile(r"^(.+?) (\d+) minuto[s]? (\d+) segundo[s]?$")
    NOISE = {
        "Baixar", "Excluir", "Use enter/espaço para obter mais opções.",
        "O conteúdo gerado por IA pode estar incorreto",
        "Transcrição. Use as setas para navegar entre as entradas da transcrição.",
    }

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    entries = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if line in NOISE:
            i += 1
            continue

        # Detectar início de bloco: nome do speaker seguido de "N minutos M segundos"
        # padrão: linha[i] = "Nome Sobrenome", linha[i+1] = "N minutos M segundos", linha[i+2] = "H:MM:SS"
        if (i + 2 < len(lines)
                and WRITTEN_TIME_RE.match(lines[i + 1])
                and TIME_RE.match(lines[i + 2])):
            author = line
            wm = WRITTEN_TIME_RE.match(lines[i + 1])
            total_secs = int(wm.group(1)) * 60 + int(wm.group(2))
            h, m, s = total_secs // 3600, (total_secs % 3600) // 60, total_secs % 60
            ts = f"{h}:{m:02d}:{s:02d}"
            i += 3  # pular nome + minutos + HH:MM:SS

            # Pular linha "Nome Sobrenome N minutos M segundos" repetida
            if i < len(lines) and SPEAKER_TIME_RE.match(lines[i]):
                i += 1

            # Coletar texto da fala
            speech = []
            while i < len(lines):
                l = lines[i]
                if not l or l in NOISE:
                    i += 1
                    continue
                if WRITTEN_TIME_RE.match(l) or TIME_RE.match(l) or SPEAKER_TIME_RE.match(l):
                    break
                # Próximo speaker: linha seguinte é tempo escrito?
                if (i + 1 < len(lines) and WRITTEN_TIME_RE.match(lines[i + 1])):
                    speech.append(l)
                    i += 1
                    break
                # Marcadores especiais
                if "começou a transcrição" in l or "parou a transcrição" in l:
                    break
                speech.append(l)
                i += 1

            text = " ".join(speech).strip()
            if text:
                entries.append({"autor": author, "ts": ts, "texto": text})
            continue

        # Marcadores de início/fim
        if "começou a transcrição" in line:
            entries.append({"autor": "", "ts": "0:00:00", "texto": f"[{line}]"})
        elif "parou a transcrição" in line:
            entries.append({"autor": "", "ts": "end", "texto": f"[{line}]"})

        i += 1

    return entries


def format_output(entries: list[dict]) -> list[str]:
    lines = ["# fonte: transcript"]
    for e in entries:
        if e["autor"]:
            lines.append(f"\n{e['autor']} ({e['ts']})")
            lines.append(e["texto"])
        else:
            lines.append(f"\n{e['texto']}")
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Uso: read_transcript.py <conversationId> <saida.txt>", file=sys.stderr)
        sys.exit(1)

    conv_id = sys.argv[1]
    saida = Path(sys.argv[2])

    if not re.match(r"^19:", conv_id):
        print(f"conversationId inválido: {conv_id}", file=sys.stderr)
        sys.exit(1)

    saida.parent.mkdir(parents=True, exist_ok=True)

    # Verificar sessão
    session = get_session_name(strict=False)
    if not session:
        saida.write_text("# fonte: transcript-erro — sem sessão playwright com Teams\n", encoding="utf-8")
        print("Erro: nenhuma sessão playwright. Rode: python3 tools/attach.py", file=sys.stderr)
        sys.exit(1)

    print("Abrindo chat...", file=sys.stderr)
    if not find_or_open_chat(conv_id):
        saida.write_text("# fonte: transcript-erro — não foi possível abrir o chat\n", encoding="utf-8")
        print("Erro: não foi possível abrir o chat no Teams.", file=sys.stderr)
        sys.exit(1)

    print("Navegando para Recapitular → Transcrição...", file=sys.stderr)
    if not navigate_to_transcript():
        saida.write_text("# fonte: sem-transcript — aba Transcrição não encontrada\n", encoding="utf-8")
        print("Info: aba Transcrição não encontrada (chat não é de reunião ou sem transcrição).", file=sys.stderr)
        sys.exit(0)

    print("Localizando iframe da transcrição...", file=sys.stderr)
    frame_idx = get_transcript_frame_index()
    if frame_idx is None:
        saida.write_text("# fonte: transcript-erro — iframe da transcrição não encontrado\n", encoding="utf-8")
        print("Erro: iframe da transcrição não encontrado.", file=sys.stderr)
        sys.exit(1)

    print(f"Lendo transcrição (frame {frame_idx}, scroll iterativo)...", file=sys.stderr)
    raw_text = read_transcript_full(frame_idx)
    if not raw_text:
        saida.write_text("# fonte: transcript-erro — falha ao ler o conteúdo do iframe\n", encoding="utf-8")
        print("Erro: não foi possível ler o conteúdo da transcrição.", file=sys.stderr)
        sys.exit(1)

    entries = parse_transcript_structured(raw_text)
    if not entries:
        # Fallback: gravar texto bruto limpo
        lines = ["# fonte: transcript-raw (parse estruturado falhou)"]
        lines += [l for l in raw_text.splitlines() if l.strip()]
        saida.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Transcrição gravada (raw) em {saida}", file=sys.stderr)
        sys.exit(0)

    output = format_output(entries)
    saida.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"Transcrição gravada: {len(entries)} falas em {saida}")


if __name__ == "__main__":
    main()
