"""Indice persistente/incremental, migracion de editor.db antiguas, columnas materializadas, misiones agregadas, busqueda en streaming, registro y robustez."""
import json, os, sqlite3, threading, time
import pytest
from conftest import necesita_repo, HOJA, REPO
from gridania_editor import busqueda, clases, flujo, indexer, registro


def escribir(raiz, ruta, filas):
    p = os.path.join(raiz, *ruta.split('/')); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'w', encoding='utf-8').write(''.join(json.dumps(f, ensure_ascii=False, separators=(',', ':')) + '\n' for f in filas))
    viejo = time.time() - 3600; os.utime(p, (viejo, viejo))     # mtime antiguo: sin «racy», la firma es estable


def montar(tmp_path, R):
    """repo sintetico de dos hojas (quest y Item) + una traduccion; devuelve (repo, ed)"""
    G = R.G
    repo, ed = str(tmp_path / 'repo'), str(tmp_path / 'ed')
    ja = {1: 'こんにちは', 2: 'さようなら', 3: 'ありがとう'}
    for hoja in ('quest/000/Q1', 'Item'):
        escribir(repo, 'textos/ja/%s.jsonl' % hoja, [{'row': r, 'sub': None, 'col': 0, 'text': t} for r, t in ja.items()])
        escribir(repo, 'textos/fr/%s.jsonl' % hoja, [{'row': r, 'sub': None, 'col': 0, 'text': 'fr%d' % r} for r in ja])
        escribir(repo, 'traducciones/%s.jsonl' % hoja, [{'row': 1, 'sub': None, 'col': 0, 'es': ['hola'], 'estado': 'traducida', 'h': G.hash_ja(ja[1]), 'origen': 'fr-ja-retrad'}])
    return repo, ed


@necesita_repo
def test_indice_persistente_e_incremental(tmp_path, R):
    repo, ed = montar(tmp_path, R)
    base = indexer.Base(str(tmp_path / 'db.sqlite'))
    m = indexer.indexar(R, base, repo, repo, ed, lambda m: None)
    assert m['celdas'] == 6 and not m['incremental'] and indexer.estado_indice(R, base, repo, repo, ed)['vigente']
    ids = {(r['hoja'], r['row']): r['id'] for r in base.q('SELECT id,hoja,row FROM celdas')}
    # sin cambios: no reindexa
    m2 = indexer.indexar(R, base, repo, repo, ed, lambda m: None)
    assert m2.get('sin_cambios') and m2['celdas'] == 6
    # cambia SOLO la hoja Item (japones nuevo): incremental, la otra no se toca y los ids de Item se conservan
    G = R.G
    escribir(repo, 'textos/ja/Item.jsonl', [{'row': r, 'sub': None, 'col': 0, 'text': t} for r, t in {1: 'こんにちは', 2: 'さようなら', 3: 'ありがとうございます'}.items()])
    est = indexer.estado_indice(R, base, repo, repo, ed); assert not est['vigente'] and est['hojas_cambiadas'] == 1
    base.x("UPDATE celdas SET es='MARCA' WHERE hoja='quest/000/Q1' AND row=2")   # prueba de que la hoja intacta no se reescribe
    m3 = indexer.indexar(R, base, repo, repo, ed, lambda m: None)
    assert m3['incremental'] and m3['hojas_reindexadas'] == 1 and m3['celdas'] == 6
    assert base.q("SELECT es FROM celdas WHERE hoja='quest/000/Q1' AND row=2")[0]['es'] == 'MARCA'
    assert {(r['hoja'], r['row']): r['id'] for r in base.q('SELECT id,hoja,row FROM celdas')} == ids
    assert base.q("SELECT ja FROM celdas WHERE hoja='Item' AND row=3")[0]['ja'] == 'ありがとうございます'
    # forzar reindexa todo
    assert not indexer.indexar(R, base, repo, repo, ed, lambda m: None, forzar=True)['incremental']
    assert base.q("SELECT es FROM celdas WHERE hoja='quest/000/Q1' AND row=2")[0]['es'] == ''


@necesita_repo
def test_cancelar_conserva_indice_anterior(tmp_path, R):
    repo, ed = montar(tmp_path, R)
    base = indexer.Base(str(tmp_path / 'db.sqlite'))
    indexer.indexar(R, base, repo, repo, ed, lambda m: None)
    ev = threading.Event(); ev.set()
    with pytest.raises(indexer.Cancelado):
        indexer.indexar(R, base, repo, repo, ed, lambda m: None, forzar=True, cancelar=ev)
    assert base.q('SELECT COUNT(*) n FROM celdas')[0]['n'] == 6 and indexer.estado_indice(R, base, repo, repo, ed)['vigente']


@necesita_repo
def test_paralelo_igual_que_secuencial(tmp_path, R):
    repo, ed = montar(tmp_path, R)
    a = indexer.Base(str(tmp_path / 'a.db')); b = indexer.Base(str(tmp_path / 'b.db'))
    indexer.indexar(R, a, repo, repo, ed, lambda m: None, procesos=1)
    msgs = []
    indexer.indexar(R, b, repo, repo, ed, msgs.append, procesos=2, umbral_paralelo=0)
    assert any('en 2 procesos' in m for m in msgs)       # se anuncio el reparto en procesos
    assert indexer.PIDS_TRABAJADORES and os.getpid() not in indexer.PIDS_TRABAJADORES    # y los resultados vinieron de procesos hijos de verdad (pid distinto)
    cols = 'id,hoja,row,sub,col,estado,h,ja,fr,es,es_json,origen,h_es,editada,clase,flujo'
    assert a.q('SELECT %s FROM celdas ORDER BY id' % cols) and [tuple(r) for r in a.q('SELECT %s FROM celdas ORDER BY id' % cols)] == [tuple(r) for r in b.q('SELECT %s FROM celdas ORDER BY id' % cols)]


@necesita_repo
def test_clase_y_flujo_materializados_sobreviven_al_reindexado(tmp_path, R):
    repo, ed = montar(tmp_path, R)
    base = indexer.Base(str(tmp_path / 'db.sqlite')); f = flujo.Flujo(str(tmp_path / 'flujo.json')); base.vincular_flujo(f)
    f.poner([('Item', 1, None, 0), ('no/existe', 1, None, 0)], 'hecho')
    indexer.indexar(R, base, repo, repo, ed, lambda m: None)
    assert {r['hoja']: r['clase'] for r in base.q('SELECT DISTINCT hoja, clase FROM celdas')} == {'quest/000/Q1': 'Misiones', 'Item': 'Objetos'}
    assert indexer.contadores_flujo(base) == {'por_hacer': 0, 'hecho': 1, 'sin': 5}
    f.poner([('Item', 1, None, 0)], 'sin'); f.poner([('quest/000/Q1', 3, None, 0)], 'por_hacer')
    assert indexer.contadores_flujo(base) == {'por_hacer': 1, 'hecho': 0, 'sin': 5}
    # importar TSV resincroniza todo
    f.importar_texto('hoja\trow\tsub\tcol\testado\nItem\t2\t\t0\thecho\n', reemplazar=True)
    assert indexer.contadores_flujo(base) == {'por_hacer': 0, 'hecho': 1, 'sin': 5}


def crear_base_antigua(ruta):
    """editor.db del esquema anterior: sin columnas clase/flujo ni tabla hojas_idx"""
    con = sqlite3.connect(ruta)
    con.executescript('''CREATE TABLE celdas (id INTEGER PRIMARY KEY, hoja TEXT NOT NULL, row INTEGER NOT NULL, sub INTEGER, col INTEGER NOT NULL,
      estado TEXT NOT NULL, h TEXT, ja TEXT, fr TEXT, es TEXT, es_json TEXT, origen TEXT, h_es TEXT, editada INTEGER DEFAULT 0);
      CREATE INDEX i_estado ON celdas(estado); CREATE INDEX i_hoja ON celdas(hoja, row, col); CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);''')
    con.executemany('INSERT INTO celdas(hoja,row,sub,col,estado,h,ja,fr,es,es_json,origen,h_es,editada) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', [
        ('quest/000/Q1', 1, None, 0, 'verde', 'h1', 'ja1', 'fr1', 'editada por mi', json.dumps(['editada por mi']), 'sesion', 'h1', 1),
        ('quest/000/Q1', 2, None, 0, 'rojo', 'h2', 'ja2', 'fr2', '', None, None, None, 0),
        ('ENpcResident', 1, 0, 0, 'verde', 'h3', 'ja3', 'fr3', 'es3', json.dumps(['es3']), 'fr-ja-retrad', 'h3', 0)])
    con.execute("INSERT INTO meta VALUES ('indexado', ?)", (json.dumps({'celdas': 3, 'contadores': {'rojo': 1, 'naranja': 0, 'verde': 2, 'blanco': 0}}),))
    con.commit(); con.close()


@necesita_repo
def test_migracion_de_editor_db_antigua(tmp_path):
    from gridania_editor.aplicacion import Aplicacion
    home = tmp_path / 'home'; home.mkdir(); crear_base_antigua(str(home / 'editor.db'))
    json.dump({'quest/000/Q1|2||0': 'por_hacer', 'ENpcResident|1|0|0': 'hecho', 'huerfana|1||0': 'hecho'}, open(home / 'flujo.json', 'w'))
    a = Aplicacion(str(home), repo_override=str(tmp_path / 'sin_repo'), diferir=True)
    assert set(a.base.migrados) == {'clase', 'flujo'} and not a.arranque['listo']
    a.base.migrar_datos(); a.base.vincular_flujo(a.flujo)          # lo que hace arrancar_fondo()
    filas = {(r['hoja'], r['row']): r for r in a.base.q('SELECT * FROM celdas')}
    assert filas[('quest/000/Q1', 1)]['es'] == 'editada por mi' and filas[('quest/000/Q1', 1)]['editada'] == 1 and filas[('quest/000/Q1', 1)]['origen'] == 'sesion'
    assert filas[('quest/000/Q1', 1)]['clase'] == 'Misiones' and filas[('ENpcResident', 1)]['clase'] == 'Dialogo de PNJ'
    assert filas[('quest/000/Q1', 2)]['flujo'] == 'por_hacer' and filas[('ENpcResident', 1)]['flujo'] == 'hecho' and filas[('quest/000/Q1', 1)]['flujo'] == 'sin'
    assert indexer.meta(a.base)['celdas'] == 3
    assert indexer.listar(a.base, clase='Misiones', flujo='por_hacer')[0] == 1
    # reabrir ya migrada no rehace nada y conserva todo
    a.base.cerrar(); b = indexer.Base(str(home / 'editor.db')); assert b.migrados == []
    assert b.q("SELECT flujo FROM celdas WHERE hoja='ENpcResident'")[0]['flujo'] == 'hecho'
    # base antigua sin firmas: funciona, pero el estado dice que conviene actualizar
    assert indexer.estado_indice(None, b, str(tmp_path), str(tmp_path), str(tmp_path / 'ed'))['vigente'] is False


@necesita_repo
def test_misiones_consulta_agregada_igual_que_calculo_ingenuo(tmp_path, mini_repo):
    from gridania_editor.aplicacion import Aplicacion
    a = Aplicacion(str(tmp_path / 'home'), repo_override=mini_repo); a._indexar(lambda m: None)
    ids = [r['id'] for r in a.base.q('SELECT id FROM celdas WHERE hoja=? ORDER BY id LIMIT 7', (HOJA,))]
    a.flujo_marcar({'estado': 'hecho', 'ids': ids[:4]}); a.flujo_marcar({'estado': 'por_hacer', 'ids': ids[4:]})
    a.flujo.poner([('no/existe', 1, None, 0)], 'hecho')
    m = a.misiones()['misiones'][0]
    tot = a.base.q('SELECT COUNT(*) n FROM celdas WHERE hoja=?', (HOJA,))[0]['n']
    assert (m['hecho'], m['por_hacer'], m['total']) == (4, 3, tot) and m['verde'] + m['rojo'] + m['naranja'] + m['blanco'] == tot
    # una sola consulta SQL agregada (no N+1)
    n = []; a.base.con.set_trace_callback(lambda s: n.append(s)); a.misiones(); a.base.con.set_trace_callback(None)
    assert len([s for s in n if s.lstrip().upper().startswith('SELECT')]) == 1


@necesita_repo
def test_busqueda_streaming_igual_que_memoria(tmp_path, R):
    repo, ed = montar(tmp_path, R)
    base = indexer.Base(str(tmp_path / 'db.sqlite')); indexer.indexar(R, base, repo, repo, ed, lambda m: None)
    mem = busqueda.Indice()
    for r in base.q('SELECT id,hoja,row,sub,col,estado,ja,fr,es FROM celdas ORDER BY id'): mem.anadir(dict(r))
    sql = busqueda.Indice.desde_base(base)
    assert sql.filas == []                                           # nada en RAM
    for kw in (dict(texto='HOLA'), dict(texto='こんにちは', campos=['ja']), dict(texto='fr2', campos=['fr']), dict(texto='ありがと', campos=['ja'], hoja='Item'),
               dict(texto='o', modo='palabra'), dict(texto='fr', modo='regex'), dict(texto='hola', mayus=True), dict(texto='hola', clase='Objetos', estados=['verde'])):
        q = busqueda.Consulta(**kw)
        a = mem.buscar(q); b = sql.buscar(q)
        assert a['total'] == b['total'] and [r['id'] for r in a['resultados']] == [r['id'] for r in b['resultados']], kw
    assert sql.buscar(busqueda.Consulta('こんにちは'))['total'] == 2
    # prefiltro: japones/digitos sin plegado -> instr; letras latinas sin distinguir -> sin prefiltro (se pliega en Python)
    assert busqueda.Indice._prefiltro(busqueda.Consulta('こんにちは')) == 'こんにちは' and busqueda.Indice._prefiltro(busqueda.Consulta('Camara')) is None
    assert busqueda.Indice._prefiltro(busqueda.Consulta('Camara', mayus=True, tildes=True)) == 'Camara' and busqueda.Indice._prefiltro(busqueda.Consulta('が')) is None


def test_registro_a_fichero_rotativo(tmp_path):
    import logging
    lg = logging.getLogger('gridania'); previos = list(lg.handlers); listo = getattr(lg, '_ge_listo', False)
    try:
        lg._ge_listo = False
        registro.iniciar(str(tmp_path), '9.9.9', consola=False)
        with registro.fase('prueba'): pass
        with pytest.raises(ValueError):
            with registro.fase('rota'): raise ValueError('x')
        for h in lg.handlers: h.flush()
        txt = open(registro.ruta_log(str(tmp_path)), encoding='utf-8').read()
        assert 'arranque: editor 9.9.9' in txt and 'fase prueba:' in txt and 'FALLO' in txt
    finally:
        for h in list(lg.handlers):
            if h not in previos: lg.removeHandler(h); h.close()
        lg._ge_listo = listo
        import sys, threading
        sys.excepthook = sys.__excepthook__; threading.excepthook = threading.__excepthook__


@necesita_repo
def test_servidor_http_caido_termina_el_proceso(tmp_path, mini_repo, monkeypatch):
    from gridania_editor.aplicacion import Aplicacion
    from gridania_editor.servidor import Servidor
    a = Aplicacion(str(tmp_path / 'home'), repo_override=mini_repo)
    s = Servidor(a)
    def boom(*x, **k): raise OSError('socket roto')
    monkeypatch.setattr(s.httpd, 'serve_forever', boom)
    s.arrancar()
    assert s.salir.wait(5) and 'socket roto' in s.fallo
    from gridania_editor import app as app_mod
    assert app_mod._salida(s) == 2


@necesita_repo
def test_tarea_indexar_cancelable_y_progreso(tmp_path, mini_repo):
    from gridania_editor.aplicacion import Aplicacion
    a = Aplicacion(str(tmp_path / 'home'), repo_override=mini_repo)
    a.tarea_indexar()
    for _ in range(200):
        t = a.tarea.ver()
        if t['estado'] != 'ejecutando': break
        time.sleep(0.05)
    assert t['estado'] == 'ok' and t['cancelable'] is True and 'progreso' in t
    assert a.refrescar_vigencia()['motivo'] in ('ok', 'cambios')     # ficheros recien copiados: «racy», puede no darse por vigente
    # sin tarea en curso no hay nada que cancelar
    assert a.tarea_cancelar() == {'cancelada': False}


@necesita_repo
def test_paralelo_roto_cae_a_un_proceso_sin_duplicar(tmp_path, R, monkeypatch):
    repo, ed = montar(tmp_path, R)
    class Roto(object):
        def __init__(self, *a, **k): pass
        def submit(self, *a, **k): raise __import__('concurrent.futures').futures.BrokenExecutor('trabajador muerto')
        def shutdown(self, *a, **k): pass
    monkeypatch.setattr(indexer.concurrent.futures, 'ProcessPoolExecutor', Roto)
    base = indexer.Base(str(tmp_path / 'db.sqlite')); msgs = []
    m = indexer.indexar(R, base, repo, repo, ed, msgs.append, procesos=3, umbral_paralelo=0)
    assert any('paralelo no disponible' in x for x in msgs) and m['celdas'] == 6 and base.q('SELECT COUNT(*) n FROM celdas')[0]['n'] == 6


# ---------------------------------------------------------------- revision adversarial: cierre, ocupacion, migracion interrumpida, instancia unica
@necesita_repo
def test_migracion_interrumpida_se_rehace_en_el_siguiente_arranque(tmp_path):
    ruta = str(tmp_path / 'editor.db'); crear_base_antigua(ruta)
    b = indexer.Base(ruta)
    assert 'clase' in b.migrados and b.q("SELECT 1 FROM meta WHERE k=?", (indexer.Base.MARCA_MIGRACION,))
    def muere(fase, hecho=0, total=0):
        if fase == 'migrando base de datos': raise KeyboardInterrupt('proceso muerto a mitad')
    with pytest.raises(KeyboardInterrupt): b.migrar_datos(muere)
    assert not b.ocupada.is_set()                                      # el cerrojo/ocupacion no queda retenido
    b.con.close()
    c = indexer.Base(ruta)                                             # siguiente arranque: detecta la marca aunque la columna ya exista
    assert 'clase' in c.migrados
    c.migrar_datos()
    assert c.migrados == [] and not c.q("SELECT 1 FROM meta WHERE k=?", (indexer.Base.MARCA_MIGRACION,))
    assert {r['hoja']: r['clase'] for r in c.q('SELECT DISTINCT hoja, clase FROM celdas')} == {'quest/000/Q1': 'Misiones', 'ENpcResident': 'Dialogo de PNJ'}
    assert indexer.Base(ruta).migrados == []


@necesita_repo
def test_estado_responde_durante_la_migracion(tmp_path):
    from gridania_editor.aplicacion import Aplicacion
    home = tmp_path / 'home'; home.mkdir(); crear_base_antigua(str(home / 'editor.db'))
    a = Aplicacion(str(home), repo_override=str(tmp_path / 'sin_repo'), diferir=True)
    vistos = []
    def av(fase, hecho=0, total=0):
        a.arranque.update(fase=fase, hecho=hecho, total=total)
        r = {}
        t = threading.Thread(target=lambda: r.update(a.estado()), daemon=True); t.start(); t.join(5)
        vistos.append((fase, not t.is_alive(), r.get('arranque', {}).get('fase'), r.get('arranque', {}).get('ocupada')))
        with pytest.raises(indexer.Ocupada): a.base.x('UPDATE celdas SET es=es')      # edicion: mensaje claro, no «database is locked»
    a.base.migrar_datos(av)
    assert vistos and all(v[1] for v in vistos) and all(v[2] == v[0] and v[3] for v in vistos)


@necesita_repo
def test_edicion_y_flujo_durante_el_indexado(tmp_path, mini_repo):
    from gridania_editor.aplicacion import Aplicacion
    a = Aplicacion(str(tmp_path / 'home'), repo_override=mini_repo); a._indexar(lambda m: None)
    ids = [r['id'] for r in a.base.q('SELECT id FROM celdas ORDER BY id LIMIT 3')]
    visto = {}
    def cb(msg):
        if msg.startswith('indexando 0/') and not visto:
            t0 = time.time()
            visto['lee'] = a.base.q('SELECT COUNT(*) n FROM celdas')[0]['n'] > 0       # lecturas concurrentes
            visto['estado'] = a.estado()['arranque']['ocupada']
            try: a.guardar(ids[0], 'x')
            except indexer.Ocupada as x: visto['bloqueada'] = str(x)
            a.flujo_marcar({'estado': 'hecho', 'ids': ids[:2]})                           # no congela ni da «locked»
            visto['seg'] = time.time() - t0
    a._indexar(cb, forzar=True)
    assert visto['lee'] and visto['estado'] == 'indexando' and 'no se puede editar' in visto['bloqueada'] and visto['seg'] < 5
    assert not a.base.ocupada.is_set()
    assert a.base.q("SELECT COUNT(*) n FROM celdas WHERE flujo='hecho'")[0]['n'] == 2          # las marcas se volcaron al terminar
    assert a.base.x('UPDATE celdas SET es=es')                                                  # y se vuelve a poder editar


@necesita_repo
def test_cierre_durante_indexado_cancela_y_mata_trabajadores(tmp_path, R):
    import multiprocessing
    repo, ed = montar(tmp_path, R)
    base = indexer.Base(str(tmp_path / 'db.sqlite')); ev = threading.Event()
    def cb(msg):
        if 'en 2 procesos' in msg: ev.set()           # «el usuario cierra la ventana» en pleno reparto
    with pytest.raises(indexer.Cancelado):
        indexer.indexar(R, base, repo, repo, ed, cb, procesos=2, umbral_paralelo=0, cancelar=ev)
    for _ in range(100):
        if not multiprocessing.active_children(): break
        time.sleep(0.1)
    assert not multiprocessing.active_children()      # ningun trabajador queda vivo
    assert base.q('SELECT COUNT(*) n FROM celdas')[0]['n'] == 0 and not base.ocupada.is_set()


def test_cerrar_trabajo_cancela_la_tarea_y_terminar_sale_del_proceso(tmp_path):
    import subprocess, sys
    from gridania_editor import app as app_mod
    from gridania_editor.aplicacion import Aplicacion
    a = Aplicacion(str(tmp_path / 'home'), repo_override=str(tmp_path / 'sin_repo'))
    def larga(log):
        while not a.tarea.cancelar_ev.is_set(): time.sleep(0.02)
        raise indexer.Cancelado('x')
    a.tarea.iniciar('indexar', larga, cancelable=True)
    t0 = time.time(); app_mod.cerrar_trabajo(a); assert a.tarea.estado == 'cancelada' and time.time() - t0 < 3
    r = subprocess.run([sys.executable, '-I', '-c', 'import sys; sys.path.insert(0, %r); import threading, time; threading.Thread(target=lambda: time.sleep(60)).start(); '
                        'from gridania_editor.app import terminar; terminar(3)' % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))], timeout=30)
    assert r.returncode == 3                                                                   # sale aunque queden hilos no demonio


@necesita_repo
def test_refirmar_no_da_por_vigente_una_hoja_desactualizada(tmp_path, R):
    repo, ed = montar(tmp_path, R)
    base = indexer.Base(str(tmp_path / 'db.sqlite')); indexer.indexar(R, base, repo, repo, ed, lambda m: None)
    firma0 = base.q("SELECT firma FROM hojas_idx WHERE hoja='Item'")[0]['firma']
    # 1) la fuente cambio antes de la edicion: la hoja sigue pendiente de reindexar
    previa = indexer.firma_actual(base, 'Item')
    escribir(repo, 'textos/ja/Item.jsonl', [{'row': 1, 'sub': None, 'col': 0, 'text': 'cambiado'}])
    previa2 = indexer.firma_actual(base, 'Item')
    escribir(ed, 'traducciones/Item.jsonl', [{'row': 1, 'sub': None, 'col': 0, 'es': ['x'], 'estado': 'traducida', 'h': 'h', 'origen': 'sesion'}])
    indexer.refirmar(base, 'Item', previa2)
    assert base.q("SELECT firma FROM hojas_idx WHERE hoja='Item'")[0]['firma'] == firma0
    assert indexer.estado_indice(R, base, repo, repo, ed)['hojas_cambiadas'] >= 1
    # 2) hoja al dia + firma racy: se actualiza y se conserva el '!'
    indexer.indexar(R, base, repo, repo, ed, lambda m: None)
    base.x("UPDATE hojas_idx SET firma=firma||'!' WHERE hoja='Item'")
    previa = indexer.firma_actual(base, 'Item')
    escribir(ed, 'traducciones/Item.jsonl', [{'row': 2, 'sub': None, 'col': 0, 'es': ['y'], 'estado': 'traducida', 'h': 'h', 'origen': 'sesion'}])
    indexer.refirmar(base, 'Item', previa)
    nueva = base.q("SELECT firma FROM hojas_idx WHERE hoja='Item'")[0]['firma']
    assert nueva.endswith('!') and nueva[:-1] == indexer.firma_actual(base, 'Item')


def test_instancia_unica_y_reapertura(tmp_path, monkeypatch):
    import logging
    from gridania_editor import app as app_mod, instancia
    home = str(tmp_path)
    f = instancia.adquirir(home); assert f is not None
    assert instancia.adquirir(home) is None                      # segundo lanzamiento: no crea otro proceso
    instancia.publicar(home, 'http://127.0.0.1:1/', 'navegador', 'k')
    abiertas = []; monkeypatch.setattr(app_mod.webbrowser, 'open', abiertas.append)
    monkeypatch.setattr(instancia, 'responde', lambda info, timeout=2.0: True)
    assert app_mod._ya_abierto(home, logging.getLogger('gridania')) == 0 and abiertas == ['http://127.0.0.1:1/']
    monkeypatch.setattr(instancia, 'responde', lambda info, timeout=2.0: False)
    monkeypatch.setattr(app_mod, '_caja', lambda *a: None)
    abiertas.clear(); app_mod._ya_abierto(home, logging.getLogger('gridania')); assert abiertas == []     # no responde: no se abre la URL
    instancia.liberar(home, f)
    g = instancia.adquirir(home); assert g is not None; instancia.liberar(home, g)


def test_registro_tolera_fallo_de_rotacion(tmp_path, monkeypatch):
    import logging, logging.handlers
    def boom(self): raise PermissionError('log en uso por otro proceso (Windows)')
    monkeypatch.setattr(logging.handlers.RotatingFileHandler, 'doRollover', boom)
    h = registro.RotativoTolerante(str(tmp_path / 'x.log'), maxBytes=50, backupCount=1, encoding='utf-8')
    lg = logging.Logger('t'); lg.addHandler(h)
    for i in range(5): lg.warning('linea larga numero %d para forzar rotacion', i)
    h.close()
    assert open(str(tmp_path / 'x.log'), encoding='utf-8').read().count('linea larga') == 5


def test_vigilante_espera_a_webview2_y_no_abre_dos_uis(tmp_path):
    from gridania_editor import app as app_mod
    class Ev(object):
        def __init__(self): self.e = threading.Event()
        def is_set(self): return self.e.is_set()
    class Win(object):
        def __init__(self): self.events = type('E', (), {'closed': Ev()})(); self.destruida = False
        def destroy(self): self.destruida = True
    class Srv(object):
        def __init__(self): self.ui_cargada = threading.Event(); self.salir = threading.Event()
    class Ap(object):
        aviso = ''; cfg = type('C', (), {'home': str(tmp_path)})()
    # carga lenta (tras la espera inicial pero antes del maximo): NO se abre el navegador
    srv, win, ap, est, abiertas = Srv(), Win(), Ap(), {'navegador': False}, []
    threading.Timer(0.3, srv.ui_cargada.set).start()
    app_mod._vigilar_ui(srv, ap, win, est, 'u', espera=0.1, maximo=2, paso=0.05, abrir=abiertas.append)
    assert abiertas == [] and not win.destruida and not est['navegador']
    # nunca carga: se cierra la ventana propia y se abre UN navegador
    srv, win, est = Srv(), Win(), {'navegador': False}
    app_mod._vigilar_ui(srv, ap, win, est, 'u', espera=0.05, maximo=0.3, paso=0.05, abrir=abiertas.append)
    assert abiertas == ['u'] and win.destruida and est['navegador'] and 'WebView2' in ap.aviso
    # el usuario cierra la ventana mientras carga: no se abre nada
    srv, win, est, abiertas = Srv(), Win(), {'navegador': False}, []
    win.events.closed.e.set()
    app_mod._vigilar_ui(srv, ap, win, est, 'u', espera=0.05, maximo=1, paso=0.05, abrir=abiertas.append)
    assert abiertas == [] and not est['navegador']


def test_ocupacion_por_razones_no_se_pisa(tmp_path):
    b = indexer.Base(str(tmp_path / 'e.db'))
    b.ocupar(indexer.MIGRANDO); b.ocupar(indexer.INDEXANDO)
    b.liberar(indexer.INDEXANDO)
    assert b.ocupada.is_set() and b.motivo == indexer.MIGRANDO       # liberar el indexado no libera la migracion
    with pytest.raises(indexer.Ocupada): b.exigir_libre()
    b.liberar(indexer.MIGRANDO)
    assert not b.ocupada.is_set() and b.motivo == ''


def test_indexar_espera_a_la_migracion(tmp_path):
    b = indexer.Base(str(tmp_path / 'e.db')); b.ocupar(indexer.MIGRANDO)
    msgs = []; t0 = time.time()
    threading.Timer(0.4, lambda: b.liberar(indexer.MIGRANDO)).start()
    b.esperar_migracion(msgs.append, threading.Event())
    assert time.time() - t0 >= 0.3 and msgs and 'migracion' in msgs[0] and not b.ocupada.is_set()
    b.ocupar(indexer.MIGRANDO); ev = threading.Event(); ev.set()
    with pytest.raises(indexer.Ocupada): b.esperar_migracion(None, ev)


@necesita_repo
def test_indexar_libera_si_falla_conectar(tmp_path, mini_repo, R, monkeypatch):
    b = indexer.Base(str(tmp_path / 'e.db'))
    def mal(*a, **k): raise sqlite3.OperationalError('no abre')
    monkeypatch.setattr(b, 'conectar', mal)
    with pytest.raises(sqlite3.OperationalError):
        indexer.indexar(R, b, mini_repo, os.path.join(mini_repo, 'textos'), str(tmp_path / 'ed'), lambda m: None, forzar=True)
    assert not b.ocupada.is_set()


def test_instancia_obsoleta_no_responde(tmp_path):
    from gridania_editor import instancia
    assert not instancia.responde({'url': 'http://127.0.0.1:9/', 'clave': 'x'}, timeout=0.5)
    assert not instancia.responde({'url': 'http://127.0.0.1:9/'}) and not instancia.responde({})


def test_instancia_viva_responde_y_obsoleta_se_ignora(tmp_path):
    from gridania_editor import instancia, app
    import http.server, logging
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            ok = self.path == '/api/estado' and self.headers.get('X-K') == 'k'
            self.send_response(200 if ok else 401); self.end_headers(); self.wfile.write(b'{}')
        def log_message(self, *a): pass
    s = http.server.HTTPServer(('127.0.0.1', 0), H); threading.Thread(target=s.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:%d/' % s.server_port
    try:
        assert instancia.responde({'url': url, 'clave': 'k'}) and not instancia.responde({'url': url, 'clave': 'mala'})
    finally: s.shutdown()
    home = str(tmp_path / 'h'); os.makedirs(home)
    instancia.publicar(home, 'http://127.0.0.1:9/', 'navegador', 'k')       # nadie escucha y nadie tiene el cerrojo
    c = app._recuperar_obsoleta(home, logging.getLogger('t'))
    assert c is not None
    c.close()


@necesita_repo
def test_guardar_comprueba_ocupacion_una_sola_vez(tmp_path, mini_repo, monkeypatch):
    from gridania_editor.aplicacion import Aplicacion
    from gridania_editor import edits
    a = Aplicacion(str(tmp_path / 'home'), repo_override=mini_repo); a._indexar(lambda m: None)
    i = a.base.q("SELECT id FROM celdas WHERE estado='verde' ORDER BY id LIMIT 1")[0]['id']
    n = {'c': 0}; orig = a.base.exigir_libre
    def cuenta(): n['c'] += 1; orig()
    monkeypatch.setattr(a.base, 'exigir_libre', cuenta)
    reg = indexer.obtener(a.base, i); m = a.motor(); c = m.contexto(reg['hoja'], reg['row'], reg['sub'], reg['col'])
    r = m.evaluar(c, m.es_a_texto(c, json.loads(reg['es_json'])), 'masc', True)
    edits.guardar(a.base, a.cfg.ediciones_dir, m.R, c, r['es'])
    assert n['c'] == 1
    n['c'] = 0
    edits.guardar(a.base, a.cfg.ediciones_dir, m.R, c, r['es'], comprobar=False)
    assert n['c'] == 0
