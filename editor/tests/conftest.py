import os, shutil, sys
import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
EDITOR = os.path.dirname(AQUI)
sys.path.insert(0, EDITOR)
REPO = os.path.abspath(os.path.join(EDITOR, '..', '..'))
JUEGO = '/mnt/user-data/uploads/game-nuevo/game/sqpack/ffxiv'
HOJA = 'quest/000/ManFst002_00085'


def hay_repo():
    return os.path.exists(os.path.join(REPO, 'tools', 'py', 'construir_dat.py')) and os.path.exists(os.path.join(REPO, 'textos', 'ja', HOJA + '.jsonl'))


necesita_repo = pytest.mark.skipif(not hay_repo(), reason='sin tools/py y textos/ en el checkout')
necesita_juego = pytest.mark.skipif(not os.path.exists(os.path.join(JUEGO, '0a0000.win32.index')) or not hay_repo(), reason='sin instalacion del juego')


@pytest.fixture(scope='session')
def R():
    from gridania_editor import repo_env
    return repo_env.cargar(REPO)


@pytest.fixture()
def mini_repo(tmp_path):
    """repo minimo: tools -> enlace al real; textos ja/fr y traducciones de UNA hoja de quest"""
    r = tmp_path / 'repo'
    for sub in ('textos/ja', 'textos/fr', 'traducciones'):
        d = r / sub / 'quest' / '000'; d.mkdir(parents=True)
        shutil.copy(os.path.join(REPO, sub, HOJA + '.jsonl'), d / 'ManFst002_00085.jsonl')
    os.symlink(os.path.join(REPO, 'tools'), r / 'tools')
    (r / 'data').mkdir()
    shutil.copy(os.path.join(REPO, 'data', 'recommended-game-version.txt'), r / 'data')
    return str(r)
