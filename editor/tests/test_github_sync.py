import hashlib, io, json, os, zipfile
import pytest
from gridania_editor import github_sync as gs


class Falso(object):
    """doble de Transporte con un repo en memoria"""
    def __init__(self, ficheros, truncar=False):
        self.f = dict(ficheros); self.llamadas = []; self.truncar = truncar; self.version = 1
    def _sha(self, d): return gs.sha_blob(d)
    def _arbol(self, prefijo):
        # entradas directas bajo prefijo ('' = raiz)
        hijos = {}
        for r, d in self.f.items():
            if prefijo and not r.startswith(prefijo + '/'): continue
            resto = r[len(prefijo) + 1:] if prefijo else r
            if '/' in resto: hijos[resto.split('/')[0]] = ('tree', None)
            else: hijos[resto] = ('blob', d)
        return hijos
    def _id(self, prefijo): return 'T:' + prefijo
    def json(self, ruta):
        self.llamadas.append(ruta)
        if '/commits/' in ruta: return {'sha': 'c0mm1t%d' % self.version, 'commit': {'tree': {'sha': self._id('')}}}
        if '/git/trees/' in ruta:
            ident = ruta.split('/git/trees/')[1].split('?')[0]; rec = 'recursive' in ruta
            pref = ident[2:]
            if rec:
                if self.truncar: return {'truncated': True, 'tree': []} if True else None
                out = []
                for r, d in self.f.items():
                    if r.startswith(pref + '/'): out.append({'path': r[len(pref) + 1:], 'type': 'blob', 'sha': self._sha(d), 'size': len(d)})
                return {'truncated': False, 'tree': out}
            tree = []
            for n, (t, d) in self._arbol(pref).items():
                p = (pref + '/' if pref else '') + n
                tree.append({'path': n, 'type': t, 'sha': self._id(p) if t == 'tree' else self._sha(d), 'size': len(d) if d else 0})
            return {'truncated': False, 'tree': tree}
        raise AssertionError(ruta)
    def bytes(self, ruta):
        self.llamadas.append(ruta); sha = ruta.rsplit('/', 1)[1]
        for d in self.f.values():
            if self._sha(d) == sha: return d
        raise AssertionError('blob')
    def descargar(self, ruta, destino, progreso=None):
        self.llamadas.append(ruta)
        with zipfile.ZipFile(destino, 'w') as z:
            for r, d in self.f.items(): z.writestr('own-repo-abc/' + r, d)


BASE = {'traducciones/quest/000/A.jsonl': b'{"row":1}\n', 'traducciones/Addon.jsonl': b'x\n', 'data/glosario-propio.tsv': b'ja\tes\n', 'textos/ja/Addon.jsonl': b'ja\n',
        'textos/fr/Addon.jsonl': b'fr\n', 'tools/py/construir_dat.py': b'# c\n', 'tools/py/__pycache__/x.pyc': b'\0', 'trabajo/informes/frases_a_escribir.tsv': b'h\n',
        'trabajo/informes/otro.tsv': b'no\n', 'trabajo/lotes/enorme.jsonl': b'no\n', 'README.md': b'no\n'}


def leer(d, r): return open(os.path.join(d, *r.split('/')), 'rb').read()


@pytest.mark.parametrize('umbral', [1000, 0])
def test_sync_primera_vez_e_incremental(tmp_path, umbral):
    home = tmp_path / 'h'; dest = home / 'repo'; home.mkdir()
    t = Falso(BASE); log = []
    info = gs.sincronizar(t, 'own/repo', 'main', str(home), str(dest), log.append, umbral_zip=umbral)
    assert info['via'] == ('blobs' if umbral else 'zip') and info['ficheros'] == 7
    assert leer(dest, 'traducciones/Addon.jsonl') == b'x\n' and leer(dest, 'trabajo/informes/frases_a_escribir.tsv') == b'h\n'
    for no in ('trabajo/informes/otro.tsv', 'trabajo/lotes/enorme.jsonl', 'README.md', 'tools/py/__pycache__/x.pyc'):
        assert not os.path.exists(os.path.join(dest, *no.split('/')))
    # sin cambios: nada que descargar
    assert gs.sincronizar(t, 'own/repo', 'main', str(home), str(dest), log.append, umbral_zip=umbral)['descargados'] == 0
    # un cambio + un borrado
    t.f['traducciones/Addon.jsonl'] = b'y\n'; del t.f['textos/fr/Addon.jsonl']; t.version = 2
    i2 = gs.sincronizar(t, 'own/repo', 'main', str(home), str(dest), log.append, umbral_zip=1000)
    assert i2['descargados'] == 1 and i2['borrados'] == 1 and i2['via'] == 'blobs'
    assert leer(dest, 'traducciones/Addon.jsonl') == b'y\n' and not os.path.exists(os.path.join(dest, 'textos', 'fr', 'Addon.jsonl'))
    # un fichero borrado a mano se vuelve a bajar
    os.remove(os.path.join(dest, 'data', 'glosario-propio.tsv'))
    assert gs.sincronizar(t, 'own/repo', 'main', str(home), str(dest), log.append, umbral_zip=1000)['descargados'] == 1


def test_arbol_truncado_recorre_directorios(tmp_path):
    t = Falso(BASE, truncar=True); home = tmp_path / 'h'; home.mkdir()
    info = gs.sincronizar(t, 'own/repo', 'main', str(home), str(home / 'repo'), lambda m: None, umbral_zip=1000)
    assert info['ficheros'] == 7


def test_sha_distinto_aborta(tmp_path):
    t = Falso(BASE)
    t.bytes = lambda ruta: b'corrupto'
    home = tmp_path / 'h'; home.mkdir()
    with pytest.raises(gs.ErrorGitHub): gs.sincronizar(t, 'own/repo', 'main', str(home), str(home / 'repo'), lambda m: None, umbral_zip=1000)


def test_token_solo_en_cabecera_y_mensajes_sin_token():
    t = gs.Transporte('ghp_SECRETO')
    r = t._req('https://api.github.com/x', gs.JSON)
    assert r.get_header('Authorization') == 'Bearer ghp_SECRETO'
    assert r.full_url == 'https://api.github.com/x' and 'ghp_SECRETO' not in r.full_url
    assert 'ghp_SECRETO' not in t._msg(404) and 'privado' in t._msg(404)
    assert t._req('https://codeload.github.com/z', gs.JSON, con_auth=False).get_header('Authorization') is None


def test_es_necesario():
    assert gs.es_necesario('textos/ja/Item.jsonl') and gs.es_necesario('tools/py/lotes/x.py') and not gs.es_necesario('textos/INDEX.csv')
    assert not gs.es_necesario('trabajo/informes/rev_x.tsv') and not gs.es_necesario('tools/py/a/__pycache__/b.py')
