"""Espaciado masivo (funciones puras), deteccion de ruta del juego, copia embebida de tools/py y vista previa (ui/vista.js con node)."""
import json, os, shutil, subprocess, pytest
from gridania_editor import espaciado, extractor, repo_env

VISTA = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gridania_editor', 'ui', 'vista.js'))
NODE = shutil.which('node')


def test_solo_saltos():
    assert espaciado.solo_saltos('Hola mundo', 'Hola<NewLine>mundo')
    assert espaciado.solo_saltos(['a b', 'c d'], ['a<NewLine>b', 'c d'])
    assert not espaciado.solo_saltos('Hola mundo', 'Hola mundos')
    assert not espaciado.solo_saltos(['a b'], ['a', 'b'])                       # cambia el n. de trozos
    assert not espaciado.solo_saltos('Hola <Gender>a<GenderElse>b<GenderEnd>', 'Hola')   # pierde macros


def test_modos_y_exclusiones():
    assert espaciado.MODOS == ('aplicar', 'quitar') and 'Balloon' in espaciado.SIEMPRE_EXCLUIDAS and 'NpcYell' in espaciado.SIEMPRE_EXCLUIDAS


def test_detectar_ruta_juego():
    ok = os.path.join('C:\\', 'SquareEnix', 'FINAL FANTASY XIV - A Realm Reborn', 'game', 'sqpack', 'ffxiv', '0a0000.win32.index')
    assert extractor.detectar_ruta_juego(env={}, existe=lambda p: p == ok).endswith(os.path.join('sqpack', 'ffxiv'))
    assert extractor.detectar_ruta_juego(env={}, existe=lambda p: False) == ''


def test_embebido_cargable_sin_repo(tmp_path):
    assert repo_env.raiz_embebida()
    R = repo_env.cargar(str(tmp_path / 'sin_repo'), forzar=True)
    assert hasattr(R.SS, 'modo_de') and hasattr(R.RL, 'procesar_celda')


def test_embebido_sin_textos_del_juego():
    raiz = repo_env.raiz_embebida()
    for d, _, fs in os.walk(raiz):
        if '__pycache__' in d: continue
        for f in fs: assert f.endswith(('.py', '.tsv', '.txt')), f
    assert not os.path.isdir(os.path.join(raiz, 'textos'))


@pytest.mark.skipif(not NODE, reason='sin node')
def test_vista_js(tmp_path):
    js = '''const V=require(%r);
const v={ventanas:[['Hola \\x01mundo\\x02 ####','segunda linea']],nventanas:1,nlineas:2,hablante:'Ana',caja:{tipo:'dialogo',seguro:58,duro:61,lineas:4}};
const h=V.ventanasHtml(v,{});
if(!h.includes('--w:61')||!h.includes('class="mac"')&&!h.includes('mac'))throw new Error('ancho/macro '+h);
if(h.includes('<NewLine'))throw new Error('etiqueta cruda');
const largo={ventanas:[['x'.repeat(62)]],nventanas:1,nlineas:1,caja:{tipo:'dialogo',seguro:58,duro:61,lineas:4}};
if(!V.ventanasHtml(largo,{}).includes('mala'))throw new Error('no avisa');
const r={vista:v,variantes:{fem:v,masc:v}};
if((V.vistaHtml(r,'ambas').match(/class="vv"/g)||[]).length!==2)throw new Error('ambas');
if((V.vistaHtml(r,'fem').match(/class="vv"/g)||[]).length!==1)throw new Error('fem');
if(V.vistaHtml({vista:v},'ambas').includes('vtit'))throw new Error('sin genero');
if(V.lineaHtml('<Foo#1> x',58,61).includes('<Foo'))throw new Error('cruda');
''' % VISTA
    f = tmp_path / 't.js'; f.write_text(js, encoding='utf-8')
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------- ejecutar/deshacer con SQLite temporal y Motor falso
import threading, types
from gridania_editor import indexer, edits


class _Cfg(object):
    def __init__(self, home): self.home = str(home); self.ediciones_dir = os.path.join(self.home, 'ed')
    def sub(self, *p): return os.path.join(self.home, *p)


class _R(object):
    class C(object):
        ORIGENES_VALIDOS = ('sesion',)
        class Rechazo(Exception): pass
        @staticmethod
        def evaluar_cadena(text, raw, e): return True
    class SS(object):
        @staticmethod
        def excluida(h): return False
        @staticmethod
        def modo_de(pf, fr): return ('libre', 58)
    class RL(object):
        CFG = types.SimpleNamespace(paginar=True, macros=True, maxwin=4, solo=False)
        # texto con '<NewLine>' = salto; incumple si la ultima linea es < 10 car.; el reflujo falso lo arregla quitando el salto
        @staticmethod
        def violaciones(s): L = s.split('<NewLine>'); return 1 if len(L) >= 2 and len(L[-1]) < 10 else 0
        @staticmethod
        def procesar_celda(text, raw, e, W, creador, clave=None, d=None):
            s = e['es']; d['antes'] = s
            if '<NewLine>' not in s: return ('sin_saltos', None, '')
            n = s.replace('<NewLine>', ' '); d['despues'] = n
            return ('cambiada', n, {'coste': (5.0, 1.0)})


class _Motor(object):
    R = _R
    def __init__(self, base): self.base = base
    def contexto(self, hoja, row, sub, col):
        c = types.SimpleNamespace(hoja=hoja, row=row, sub=sub, col=col, k=(row, sub, col), text='t', raw=None, clave='', h='h', reflujo_W=58, creador=False,
                                  pf=types.SimpleNamespace(tipo='dialogo'), fr_text='')
        return c
    def _fila(self, c, es): return {'es': es}
    def _validar(self, c, es): return True
    def sin_saltos(self, c, es): return es.replace('<NewLine>', ' ')


def _app(tmp_path):
    base = indexer.Base(str(tmp_path / 'db.sqlite'))
    for i, es in enumerate(['uno dos tres cuatro cinco seis siete ocho<NewLine>nueve', 'esta frase tiene salto largo y bueno<NewLine>y esto tambien es largo', 'sin saltos']):
        base.con.execute("INSERT INTO celdas(hoja,row,sub,col,estado,es,es_json,origen,h_es,editada) VALUES ('H',?,NULL,1,'verde',?,?,'previo-ja','h0',0)",
                         (i, es, json.dumps(es)))
    base.con.commit()
    app = types.SimpleNamespace(base=base, cfg=_Cfg(tmp_path), lock_ediciones=threading.RLock())
    m = _Motor(base); app.motor = lambda: m
    return app, base


def _filas(base): return [tuple(r) for r in base.q('SELECT row,es,es_json,origen,h_es,editada,estado FROM celdas ORDER BY row')]


def test_aplicar_solo_incumplen_y_deshacer_byte_a_byte(tmp_path):
    app, base = _app(tmp_path)
    antes = _filas(base)
    r = espaciado.ejecutar(app, 'aplicar', lambda *a: None)
    assert r['estado'] == 'completo' and r['cambiadas'] == 1                          # solo la fila 0 incumple; la 1 cumple (ultima linea larga); la 2 sin saltos
    desp = _filas(base)
    assert desp[0][2] == json.dumps('uno dos tres cuatro cinco seis siete ocho nueve') and desp[0][3] == 'sesion' and desp[1] == antes[1] and desp[2] == antes[2]
    assert os.path.exists(edits.ruta(app.cfg.ediciones_dir, 'H'))
    d = espaciado.deshacer(app, lambda *a: None)
    assert d['restauradas'] == 1 and _filas(base) == antes                              # es, es_json, origen, h_es, editada restaurados
    assert not os.path.exists(edits.ruta(app.cfg.ediciones_dir, 'H'))                  # la fila de ediciones nueva se retira
    assert espaciado.ultimo_registro(app.cfg)[1] is None


def test_guardado_concurrente_entre_calculo_y_escritura(tmp_path):
    app, base = _app(tmp_path)
    m = app.motor(); orig = m.sin_saltos
    def espaciar_y_editar(c, es):                                                      # el usuario guarda la celda 0 mientras el espaciado calcula
        base.con.execute("UPDATE celdas SET es_json=? WHERE row=0", (json.dumps('editado por el usuario'),)); base.con.commit()
        return orig(c, es)
    m.sin_saltos = espaciar_y_editar
    r = espaciado.ejecutar(app, 'quitar', lambda *a: None)
    assert r['categorias'].get('cambiada_durante', 0) >= 1
    assert json.loads(base.q('SELECT es_json FROM celdas WHERE row=0')[0]['es_json']) == 'editado por el usuario'


def test_ultimo_registro_en_curso_tras_cuelgue(tmp_path):
    cfg = _Cfg(tmp_path); d = espaciado.dir_registros(cfg); os.makedirs(d)
    open(os.path.join(d, 'x_aplicar.jsonl'), 'w').write(json.dumps({'tipo': 'cabecera'}) + '\n' + json.dumps({'hoja': 'H'}) + '\n')
    json.dump({'estado': 'en_curso', 'deshecho': False, 'registro': 'x_aplicar.jsonl', 'modo': 'aplicar'}, open(os.path.join(d, 'x_aplicar.resumen.json'), 'w'))
    assert espaciado.ultimo_registro(cfg)[1]['cambiadas'] == 1


def test_n0_en_creador_y_sin_aviso_4_lineas():
    from gridania_editor import celda
    src = open(celda.__file__, encoding='utf-8').read()
    assert "'descripcion') or c.hoja == 'Lobby' or c.hoja.startswith('CharaMake')) else 4" in src
    if NODE:
        js = "const V=require(%r);const l=['a','b','c','d','e','f'];const v={ventanas:[l],nventanas:1,nlineas:6,caja:{tipo:'descripcion',seguro:49,duro:51,lineas:4,creador:true}};" \
             "if(V.ventanasHtml(v,{}).includes('mas de'))throw new Error('aviso');v.caja={tipo:'dialogo',seguro:58,duro:61,lineas:4};if(!V.ventanasHtml(v,{}).includes('mas de'))throw new Error('falta');" % VISTA
        r = subprocess.run([NODE, '-e', js], capture_output=True, text=True); assert r.returncode == 0, r.stderr
