"""Importa desde GitHub (API, sin git) lo que necesita el editor: traducciones/, data/, textos/ja, textos/fr, tools/py y unas pocas tablas de trabajo/informes.
Incremental por sha de blob (manifiesto local); si cambian muchos ficheros (primera vez) baja el zipball del commit y extrae solo lo necesario.
El token solo viaja en la cabecera Authorization de api.github.com; nunca se escribe en logs ni en mensajes de error."""
import concurrent.futures, hashlib, json, os, tempfile, time, urllib.error, urllib.request, zipfile

API = 'https://api.github.com'
PREFIJOS = ['traducciones', 'data', 'textos/ja', 'textos/fr', 'tools/py']
INFORMES = ('frases_a_escribir.tsv', 'frases_say_canonicas.tsv', 'frases_say_menu.tsv', 'expansion_historia.tsv', 'corpus_no_traducible.tsv')
UMBRAL_ZIP = 400
RAW = 'application/vnd.github.raw+json'
JSON = 'application/vnd.github+json'


class ErrorGitHub(Exception):
    pass


def es_necesario(ruta):
    """ruta relativa (con /) que el editor descarga"""
    if ruta.startswith('trabajo/informes/'): return ruta.count('/') == 2 and ruta.rsplit('/', 1)[1] in INFORMES
    if '/__pycache__/' in ruta or ruta.endswith('.pyc'): return False
    return any(ruta.startswith(p + '/') for p in PREFIJOS)


def sha_blob(datos):
    return hashlib.sha1(b'blob %d\x00' % len(datos) + datos).hexdigest()


class Transporte(object):
    """HTTP real. Las pruebas usan un doble con los mismos metodos."""
    def __init__(self, token='', base=API, ua='gridania-editor'):
        self.token = token; self.base = base; self.ua = ua

    def _req(self, url, accept, con_auth=True):
        h = {'Accept': accept, 'User-Agent': self.ua, 'X-GitHub-Api-Version': '2022-11-28'}
        if self.token and con_auth: h['Authorization'] = 'Bearer ' + self.token
        return urllib.request.Request(url, headers=h)

    def _abrir(self, req, timeout=120):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            raise ErrorGitHub(self._msg(e.code)) from None
        except urllib.error.URLError as e:
            raise ErrorGitHub('sin conexion con GitHub (%s)' % type(e.reason).__name__) from None

    @staticmethod
    def _msg(codigo):
        pistas = {401: 'token no valido o caducado', 403: 'acceso denegado o limite de la API (espera o revisa el token)', 404: 'no encontrado: revisa repo/rama y que el token tenga acceso al repo privado (permiso Contents: lectura)'}
        return 'GitHub respondio %d: %s' % (codigo, pistas.get(codigo, 'error'))

    def json(self, ruta):
        with self._abrir(self._req(self.base + ruta, JSON)) as r: return json.loads(r.read().decode('utf-8'))

    def bytes(self, ruta):
        with self._abrir(self._req(self.base + ruta, RAW)) as r: return r.read()

    def descargar(self, ruta, destino, progreso=None):
        """zipball: GitHub redirige a codeload; la redireccion se sigue SIN cabecera Authorization"""
        class _NoRedir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k): return None
        op = urllib.request.build_opener(_NoRedir)
        url = self.base + ruta; auth = True
        for _ in range(5):
            try:
                r = op.open(self._req(url, JSON, auth), timeout=120)
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308) and e.headers.get('Location'):
                    url = e.headers['Location']; auth = False; continue
                raise ErrorGitHub(self._msg(e.code)) from None
            except urllib.error.URLError as e:
                raise ErrorGitHub('sin conexion con GitHub (%s)' % type(e.reason).__name__) from None
            with r, open(destino, 'wb') as f:
                n = 0
                while True:
                    b = r.read(1 << 20)
                    if not b: break
                    f.write(b); n += len(b)
                    if progreso: progreso('descargando zip: %d MB' % (n >> 20))
            return n
        raise ErrorGitHub('demasiadas redirecciones')


def _hijo(arbol, nombre):
    for e in arbol.get('tree', []):
        if e['path'] == nombre: return e
    return None


def _listar_subarbol(t, repo, sha, base, salida):
    d = t.json('/repos/%s/git/trees/%s?recursive=1' % (repo, sha))
    if d.get('truncated'):   # recorrido manual por directorios
        d = t.json('/repos/%s/git/trees/%s' % (repo, sha))
        for e in d['tree']:
            if e['type'] == 'tree': _listar_subarbol(t, repo, e['sha'], base + e['path'] + '/', salida)
            elif e['type'] == 'blob': salida[base + e['path']] = (e['sha'], e.get('size', 0))
        return
    for e in d['tree']:
        if e['type'] == 'blob': salida[base + e['path']] = (e['sha'], e.get('size', 0))


def listar_remoto(t, repo, tree_sha):
    """-> {ruta: (sha, size)} de los ficheros necesarios"""
    raiz = t.json('/repos/%s/git/trees/%s' % (repo, tree_sha)); out = {}
    cache = {}
    def bajar(partes):
        nodo = raiz
        for i, p in enumerate(partes):
            k = '/'.join(partes[:i + 1])
            if k not in cache:
                e = _hijo(nodo, p)
                if e is None or e['type'] != 'tree': return None
                cache[k] = t.json('/repos/%s/git/trees/%s' % (repo, e['sha']))
            nodo = cache[k]
        return nodo
    for pref in PREFIJOS:
        partes = pref.split('/')
        padre = bajar(partes[:-1]) if len(partes) > 1 else raiz
        if padre is None: continue
        e = _hijo(padre, partes[-1])
        if e is None or e['type'] != 'tree': continue
        _listar_subarbol(t, repo, e['sha'], pref + '/', out)
    inf = bajar(['trabajo', 'informes'])
    if inf:
        for e in inf['tree']:
            r = 'trabajo/informes/' + e['path']
            if e['type'] == 'blob' and es_necesario(r): out[r] = (e['sha'], e.get('size', 0))
    return {k: v for k, v in out.items() if es_necesario(k)}


def _escribir(destino, ruta, datos):
    p = os.path.join(destino, *ruta.split('/'))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'wb') as f: f.write(datos)
    os.replace(tmp, p)


def sincronizar(t, repo, rama, home, destino, progreso=print, umbral_zip=UMBRAL_ZIP, hilos=8):
    """Deja en `destino` (home/repo) una copia parcial del repo en `rama`. -> dict resumen. Manifiesto en home/sync_manifest.json."""
    man_ruta = os.path.join(home, 'sync_manifest.json')
    manifiesto = {}
    if os.path.exists(man_ruta):
        try: manifiesto = json.load(open(man_ruta, encoding='utf-8'))
        except ValueError: manifiesto = {}
    c = t.json('/repos/%s/commits/%s' % (repo, rama))
    commit = c['sha']; tree = c['commit']['tree']['sha']
    progreso('commit %s; listando ficheros...' % commit[:10])
    remoto = listar_remoto(t, repo, tree)
    pend = [r for r, (sha, _) in remoto.items() if manifiesto.get(r) != sha or not os.path.exists(os.path.join(destino, *r.split('/')))]
    borrar = [r for r in manifiesto if r not in remoto and es_necesario(r)]
    progreso('%d ficheros remotos, %d por descargar, %d por borrar' % (len(remoto), len(pend), len(borrar)))
    via = 'nada'
    if pend and len(pend) > umbral_zip:
        via = 'zip'
        fd, tmp = tempfile.mkstemp(suffix='.zip', dir=home); os.close(fd)
        try:
            t.descargar('/repos/%s/zipball/%s' % (repo, commit), tmp, progreso)
            falta = set(pend)
            with zipfile.ZipFile(tmp) as z:
                for info in z.infolist():
                    if info.is_dir(): continue
                    ruta = info.filename.split('/', 1)[1] if '/' in info.filename else info.filename
                    if ruta in falta:
                        datos = z.read(info)
                        if sha_blob(datos) != remoto[ruta][0]: raise ErrorGitHub('sha distinto en el zip: ' + ruta)
                        _escribir(destino, ruta, datos); falta.discard(ruta)
            if falta: raise ErrorGitHub('faltan %d ficheros en el zip (p. ej. %s)' % (len(falta), sorted(falta)[0]))
        finally:
            try: os.remove(tmp)
            except OSError: pass
    elif pend:
        via = 'blobs'; hechos = [0]
        def uno(r):
            datos = t.bytes('/repos/%s/git/blobs/%s' % (repo, remoto[r][0]))
            if sha_blob(datos) != remoto[r][0]: raise ErrorGitHub('sha distinto en la descarga: ' + r)
            _escribir(destino, r, datos); hechos[0] += 1
            if hechos[0] % 50 == 0: progreso('%d/%d' % (hechos[0], len(pend)))
        with concurrent.futures.ThreadPoolExecutor(hilos) as ex:
            for f in [ex.submit(uno, r) for r in pend]: f.result()
    for r in borrar:
        try: os.remove(os.path.join(destino, *r.split('/')))
        except OSError: pass
    nuevo = {r: sha for r, (sha, _) in remoto.items()}
    tmp = man_ruta + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(nuevo, f)
    os.replace(tmp, man_ruta)
    info = {'repo': repo, 'rama': rama, 'commit': commit, 'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'descargados': len(pend), 'borrados': len(borrar), 'via': via, 'ficheros': len(remoto)}
    with open(os.path.join(home, 'sync_info.json'), 'w', encoding='utf-8') as f: json.dump(info, f, indent=1)
    progreso('listo: %d descargados (%s), %d borrados' % (len(pend), via, len(borrar)))
    return info
