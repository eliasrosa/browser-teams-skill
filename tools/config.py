"""
Helper compartilhado: configuração da skill em .data/config.json.

Lê e escreve as preferências do usuário que NÃO pertencem ao código
(paths, preferências de comportamento). O arquivo é gitignored (.data/).

Uso:
    from config import get_config, set_config, SKILL_DIR

    cfg = get_config()
    notes_dir = cfg['notes_dir']   # Path resolvido

Campos disponíveis:
    notes_dir       — onde gravar as notas de leitura (MDs por chat).
                      Default: <skill>/.data/notes/ (dentro da skill, portável).
                      Trocar para vault Obsidian: set_config({'notes_dir': '~/vault/Teams'})
    message_prefix  — prefixo adicionado no início de toda mensagem enviada pelo agente.
                      Default: '🤖 _Estagiário_ · '
                      Trocar: set_config({'message_prefix': '🤖 Bot · '})
"""

import json
from pathlib import Path

# Raiz da skill: tools/ está um nível abaixo
SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR  = SKILL_DIR / '.data'
CFG_PATH  = DATA_DIR / 'config.json'

DEFAULTS = {
    'notes_dir': str(SKILL_DIR / '.data' / 'notes'),
    'message_prefix': '🤖 _Estagiário_ · ',
    # futuras chaves:
    # 'vault_dir': '',        # caminho alternativo legado (ex: Obsidian)
    # 'session_name': '',     # PLAYWRIGHT_CLI_SESSION fixo, se necessário
}


def get_config() -> dict:
    """
    Lê o config do disco e mescla com os defaults.
    Retorna um dict com todos os campos garantidos e paths expandidos.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    stored: dict = {}
    if CFG_PATH.exists():
        try:
            stored = json.loads(CFG_PATH.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            stored = {}

    cfg = {**DEFAULTS, **stored}

    # Expandir ~ e variáveis de ambiente em campos de path
    for key in ('notes_dir',):
        if cfg.get(key):
            cfg[key] = str(Path(cfg[key]).expanduser().resolve())

    return cfg


def set_config(updates: dict) -> dict:
    """
    Atualiza campos específicos no config e persiste.
    Retorna o config completo após a atualização.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    cfg = get_config()
    cfg.update(updates)

    # Gravar apenas os campos que diferem dos defaults (config mínimo)
    to_store = {k: v for k, v in cfg.items() if str(v) != str(DEFAULTS.get(k, ''))}
    CFG_PATH.write_text(json.dumps(to_store, indent=2, ensure_ascii=False) + '\n',
                        encoding='utf-8')

    return get_config()


def notes_dir() -> Path:
    """Atalho: retorna o Path resolvido do diretório de notas."""
    return Path(get_config()['notes_dir'])


def init_notes_dir() -> Path:
    """Garante que o diretório de notas e as subpastas existem."""
    base = notes_dir()
    for sub in ('1-1', 'grupos', 'reunioes'):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


if __name__ == '__main__':
    # Uso direto: python3 config.py [set notes_dir <path>]
    import sys
    if len(sys.argv) == 4 and sys.argv[1] == 'set':
        key, val = sys.argv[2], sys.argv[3]
        result = set_config({key: val})
        print(f'{key} = {result[key]}')
        print(f'config salvo em {CFG_PATH}')
    else:
        cfg = get_config()
        print(f'config em: {CFG_PATH}')
        for k, v in cfg.items():
            default_mark = ' (default)' if str(v) == str(DEFAULTS.get(k, '')) else ''
            print(f'  {k} = {v}{default_mark}')
