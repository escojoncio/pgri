"""Genera translations.dat: fusiona repo + ediciones -> suavizado de saltos -> construir_dat (puerta) -> validar_blob_suavizado."""
import collections, contextlib, hashlib, io, json, os, shutil, sys, time
from . import edits, extractor, indexer

MIN_ENTRADAS = 757594
MAX_RECHAZOS = 43


class ErrorPuerta(Exception):
    pass


def puerta(n_entradas, n_rechazos, n_elipsis, min_entradas=MIN_ENTRADAS, max_rechazos=MAX_RECHAZOS, relajar=False):
    """-> (ok, mensajes). `…` (U+2026) siempre es fatal; entradas/rechazos solo si no se relaja (actualizacion del juego: pueden cambiar)."""
    msgs = []; ok = True
    if n_elipsis: ok = False; msgs.append('FATAL: %d entradas con «…» (U+2026)' % n_elipsis)
    if n_entradas < min_entradas:
        msgs.append('%s: %d entradas < %d' % ('AVISO (juego actualizado)' if relajar else 'FATAL', n_entradas, min_entradas)); ok = ok and relajar
    if n_rechazos > max_rechazos:
        msgs.append('%s: %d rechazos > %d' % ('AVISO (juego actualizado)' if relajar else 'FATAL', n_rechazos, max_rechazos)); ok = ok and relajar
    return ok, msgs


def clonar(src, dst, copiar=False):
    """arbol src -> dst con enlaces duros (copia si no se puede o copiar=True)"""
    for d, _, fs in os.walk(src):
        rel = os.path.relpath(d, src); o = dst if rel == '.' else os.path.join(dst, rel)
        os.makedirs(o, exist_ok=True)
        for f in fs:
            a, b = os.path.join(d, f), os.path.join(o, f)
            if copiar: shutil.copyfile(a, b); continue
            try: os.link(a, b)
            except OSError: shutil.copyfile(a, b)


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


class _Salida(io.TextIOBase):
    def __init__(self, f): self.f = f; self.buf = ''
    def write(self, s):
        self.buf += s
        while '\n' in self.buf:
            l, self.buf = self.buf.split('\n', 1)
            if l.strip(): self.f(l)
        return len(s)


def preparar_stage(R, cfg, raiz_textos, progreso):
    """stage/ = traducciones (repo + ediciones, COPIA) + textos ja/fr (enlaces) + suavizado de saltos aplicado sobre las filas. -> (ruta, n_ediciones, resumen suavizado)"""
    stage = cfg.sub('stage')
    if os.path.isdir(stage): shutil.rmtree(stage)
    os.makedirs(stage)
    progreso('copiando traducciones...')
    clonar(os.path.join(cfg.repo_dir, 'traducciones'), os.path.join(stage, 'traducciones'), copiar=True)
    n_ed = edits.fusionar_en(os.path.join(stage, 'traducciones'), cfg.ediciones_dir)
    progreso('%d filas editadas fusionadas' % n_ed)
    for idi in ('ja', 'fr'):
        s = os.path.join(raiz_textos, 'textos', idi)
        if os.path.isdir(s): clonar(s, os.path.join(stage, 'textos', idi))
    SS = R.SS
    SS.init_worker(R.raiz)
    out = os.path.join(stage, '_suave'); os.makedirs(out)
    tot = collections.Counter(); hojas = list(SS.hojas_repo(os.path.join(stage, 'traducciones')))
    for i, (hoja, path) in enumerate(hojas):
        if SS.excluida(hoja): continue
        try: _, cnt = SS.procesar_hoja((R.raiz, stage, out, hoja, path)); tot.update(cnt)
        except Exception as x: progreso('suavizado: hoja %s omitida (%s: %s)' % (hoja, type(x).__name__, x)); tot['error_hoja'] += 1
        if i % 100 == 0: progreso('suavizando %d/%d (%s)' % (i, len(hojas), hoja))
    # mezcla: las filas suavizadas sustituyen a las de stage (clave hoja+row+sub+col)
    for hoja in indexer.listar_jsonl(os.path.join(out, 'traducciones')):
        nuevo = indexer.leer_trad(os.path.join(out, 'traducciones', *hoja.split('/')) + '.jsonl')
        p = os.path.join(stage, 'traducciones', *hoja.split('/')) + '.jsonl'
        lineas = []
        with open(p, encoding='utf-8') as f:
            for l in f:
                if not l.strip(): continue
                try: j = json.loads(l); k = (j['row'], j.get('sub'), j['col'])
                except ValueError: lineas.append(l.rstrip('\n')); continue
                lineas.append(edits.linea(nuevo[k]) if k in nuevo else l.rstrip('\n'))
        with open(p + '.tmp', 'w', encoding='utf-8', newline='\n') as f: f.write('\n'.join(lineas) + '\n')
        os.replace(p + '.tmp', p)
    shutil.rmtree(out)
    return stage, n_ed, dict(tot)


def generar(R, cfg, destino, raiz_textos, progreso=print, relajar='auto', validar=True):
    """-> dict(entradas, rechazos, tamano, sha256, ruta, puerta, validacion). Lanza ErrorPuerta / ValueError."""
    game = cfg['ruta_juego']
    extractor.comprobar_ruta(game)
    if not destino: raise ValueError('elige la carpeta de destino del .dat')
    os.makedirs(destino, exist_ok=True)
    rec = ''
    try: rec = open(os.path.join(cfg.repo_dir, 'data', 'recommended-game-version.txt'), encoding='utf-8').read().strip()
    except OSError: pass
    ver = extractor.raiz_version(game)
    if relajar == 'auto': relajar = bool(ver and rec and ver != rec)
    t0 = time.time()
    stage, n_ed, suave = preparar_stage(R, cfg, raiz_textos, progreso)
    progreso('suavizado: %s' % json.dumps(suave))
    from sqpack_raw import Pack   # tools/py del repo (en sys.path)
    pk = Pack(game); cache = {}
    def exh(s):
        if s not in cache: cache[s] = pk.exh(s)
        return cache[s]
    progreso('construyendo entradas (construir_dat)...')
    avisos = []
    ok, rech, leidas = R.C.construir(stage, exh, None, avisos, False)
    mot = collections.Counter(r['motivo'] for r in rech)
    n_el = sum(1 for x in ok if '…' in x[4])
    p_ok, msgs = puerta(len(ok), len(rech), n_el, cfg['min_entradas'], cfg['max_rechazos'], bool(relajar))
    progreso('leidas %d, aceptadas %d, rechazadas %d %s' % (leidas, len(ok), len(rech), dict(mot)))
    for m in msgs: progreso(m)
    rev = os.path.join(destino, 'rechazos.csv')
    import csv
    with open(rev, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, ['hoja', 'row', 'sub', 'col', 'estado', 'motivo', 'detalle'], lineterminator='\n'); w.writeheader(); w.writerows(rech)
    res = {'entradas': len(ok), 'rechazos': len(rech), 'rechazos_por_motivo': dict(mot), 'elipsis': n_el, 'puerta': msgs, 'ediciones': n_ed, 'version_juego': ver, 'version_recomendada': rec, 'relajada': bool(relajar), 'rechazos_csv': rev}
    if not p_ok: raise ErrorPuerta('; '.join(msgs))
    lines = [R.NJ.entry_line(s, t, h, r, f_, p, st) for h, r, f_, s, t, p, st in ok]
    tmp = os.path.join(destino, 'translations.dat.tmp')
    R.BB.escribir_blob(lines, tmp, None, [(x[3], x[4]) for x in ok])
    del lines, ok
    if validar:
        progreso('validando el blob (validar_blob_suavizado)...')
        res['validacion'] = validar_blob(R, tmp, game, os.path.join(destino, 'fallos_validacion.tsv'), progreso)
        if res['validacion']['fallos']:
            raise ErrorPuerta('validar_blob_suavizado: %d fallos (ver %s); el .dat no se publica' % (res['validacion']['fallos'], os.path.join(destino, 'fallos_validacion.tsv')))
    final = os.path.join(destino, 'translations.dat')
    os.replace(tmp, final)
    res.update(ruta=final, tamano=os.path.getsize(final), sha256=sha256(final), segundos=int(time.time() - t0))
    progreso('LISTO: %d entradas, %d rechazos, %d bytes, sha256 %s' % (res['entradas'], res['rechazos'], res['tamano'], res['sha256']))
    return res


def validar_blob(R, blob, game, fallos, progreso=print):
    """ejecuta validar_blob_suavizado.main en serie (--slice 0/1: sin multiprocessing 'fork', que no existe en Windows)"""
    import validar_blob_suavizado as V
    argv = sys.argv; sys.argv = ['validar_blob_suavizado', '--blob', blob, '--game', game, '--slice', '0/1', '--fallos', fallos]
    codigo = 0; salida = _Salida(progreso)
    try:
        with contextlib.redirect_stdout(salida):
            try: V.main()
            except SystemExit as e: codigo = e.code or 0
    finally:
        sys.argv = argv
    n = 0
    if os.path.exists(fallos):
        with open(fallos, encoding='utf-8') as f: n = sum(1 for l in f if l.strip())
    return {'codigo': codigo, 'fallos': n}
