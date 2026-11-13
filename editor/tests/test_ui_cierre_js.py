"""Logica JS de cierre (beforeunload / pagehide / pageshow) extraida de ui/index.html (entre /*LOGICA_INI*/ y /*LOGICA_FIN*/) y ejecutada con node."""
import os, re, shutil, subprocess, pytest

HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gridania_editor', 'ui', 'index.html')
NODE = shutil.which('node')


def _logica():
    t = open(HTML, encoding='utf-8').read()
    m = re.search(r'/\*LOGICA_INI\*/(.*?)/\*LOGICA_FIN\*/', t, re.S); assert m; return m.group(1)


def _node(js, tmp_path):
    f = tmp_path / 't.js'; f.write_text(_logica() + '\n' + js, encoding='utf-8')
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=20); assert r.returncode == 0, r.stderr; return r.stdout.strip()


def test_el_html_registra_los_eventos_correctos():
    t = open(HTML, encoding='utf-8').read()
    assert "addEventListener('pagehide'" in t and "addEventListener('pageshow'" in t and "addEventListener('beforeunload',e=>manejarBeforeUnload" in t
    assert "addEventListener('beforeunload',avisoCierre)" not in t                       # beforeunload NO manda /api/cierre


@pytest.mark.skipif(not NODE, reason='sin node')
def test_logica_beforeunload_pagehide_pageshow(tmp_path):
    out = _node('''
const log=[];
const ev=()=>({d:false,returnValue:undefined,preventDefault(){this.d=true}});
console.log(sinGuardar('a','a',3),sinGuardar('b','a',3),sinGuardar('b','a',null));
let e=ev();manejarBeforeUnload(e,false);const limpio=[e.d,e.returnValue];
e=ev();manejarBeforeUnload(e,true);const sucio=[e.d,e.returnValue];
let n=0;manejarPageHide({persisted:true},()=>n++);manejarPageHide({persisted:false},()=>n++);
let r=0;const a=manejarPageShow({persisted:true},()=>r++),b=manejarPageShow({persisted:false},()=>r++),c=manejarPageShow(undefined,()=>r++);
console.log(JSON.stringify({limpio,sucio,n,r,a,b,c}));
''', tmp_path).splitlines()
    assert out[0] == 'false true false'
    assert out[1] == '{"limpio":[false,null],"sucio":[true,""],"n":2,"r":1,"a":true,"b":false,"c":false}'


@pytest.mark.skipif(not NODE, reason='sin node')
def test_node_check_del_script_completo(tmp_path):
    t = open(HTML, encoding='utf-8').read(); m = re.search(r'<script>(.*)</script>', t, re.S); f = tmp_path / 's.js'; f.write_text(m.group(1), encoding='utf-8')
    r = subprocess.run([NODE, '--check', str(f)], capture_output=True, text=True); assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not NODE, reason='sin node')
def test_borradores_por_celda_restauracion_y_diff(tmp_path):
    out = _node('''
const c1={hoja:'Quest',row:3,sub:null,col:1},c2={hoja:'Quest',row:3,sub:0,col:1};
const res=[claveCelda(c1),claveCelda(c2),claveCelda({hoja:'Quest',row:3,sub:undefined,col:1})];
const b={h:'h1',texto:'nuevo',base:'viejo'};
res.push(decidirBorrador(null,{h:'h1',es_texto:'x'}),
 decidirBorrador(b,{h:'h1',es_texto:'nuevo'}),       // ya igual
 decidirBorrador(b,{h:'h1',es_texto:'viejo'}),       // restaurable
 decidirBorrador(b,{h:'h2',es_texto:'viejo'}),       // el japones cambio
 decidirBorrador(b,{h:'h1',es_texto:'mas reciente'}));// la traduccion guardada es mas reciente que el borrador
// borrador de OTRA celda con la misma h: la clave es distinta, no se cruza
const mapa={};mapa[claveCelda(c1)]=b;res.push(decidirBorrador(mapa[claveCelda(c2)],{h:'h1',es_texto:'viejo'}));
res.push(JSON.stringify(diffLineas('a\\nb\\nc','a\\nB\\nc')));
res.push(puedeEnviarBorrador({cargando:false,celda:{},texto:'a',base:'b'}),puedeEnviarBorrador({cargando:true,celda:{},texto:'a',base:'b'}),puedeEnviarBorrador({cargando:false,celda:null,texto:'a',base:'b'}),puedeEnviarBorrador({cargando:false,celda:{},texto:'a',base:'a'}));
console.log(JSON.stringify(res));
''', tmp_path)
    import json
    r = json.loads(out)
    assert r[:3] == ['Quest|3||1', 'Quest|3|0|1', 'Quest|3||1']
    assert r[3:8] == ['ninguno', 'igual', 'aplicar', 'conflicto', 'conflicto'] and r[8] == 'ninguno'
    assert json.loads(r[9]) == [{'t': '=', 's': 'a'}, {'t': '-', 's': 'b'}, {'t': '+', 's': 'B'}, {'t': '=', 's': 'c'}]
    assert r[10:] == [True, False, False, False]


@pytest.mark.skipif(not NODE, reason='sin node')
def test_carrera_abrir_tick_solo_aplica_la_ultima_carga_y_no_envia_con_carga_pendiente(tmp_path):
    out = _node('''
// modelo del protocolo de abrir()/tick con las piezas reales: testigo por carga, estado atomico, sin envio con carga pendiente
selId=1;const carga=crearCarga();let celda={id:1,base:'a'},texto='editado',guardado='a',enviados=[];
function tick(){if(!puedeEnviarBorrador({cargando:carga.cargando(),celda,texto,base:guardado}))return;enviados.push([celda.id,texto])}
const pendientes={};const api=id=>new Promise(r=>pendientes[id]=r);
async function abrir(id){const tok=carga.iniciar();try{const d=await api(id);if(!carga.vigente(tok))return;selId=id;selCelda=celda={id,base:d};texto=d;guardadoTxt=guardado=d}finally{carga.fin()}}
(async()=>{
 tick();                                   // sin carga: se envia el borrador de la celda 1
 const p2=abrir(2),p3=abrir(3);            // dos aperturas solapadas
 tick();tick();                            // carga pendiente: nada se envia (no se manda el texto de 1 con el id de 2 ni al reves)
 pendientes[3]('texto3');await p3;         // la ultima termina primero
 pendientes[2]('texto2');await p2;         // la antigua llega tarde: se ignora
 tick();                                   // texto3 == base: nada que enviar
 console.log(JSON.stringify({selId,texto,guardado,celda,enviados,cargando:carga.cargando()}));
})();
''', tmp_path)
    import json
    r = json.loads(out)
    assert r['selId'] == 3 and r['texto'] == 'texto3' and r['guardado'] == 'texto3' and r['celda'] == {'id': 3, 'base': 'texto3'}
    assert r['enviados'] == [[1, 'editado']] and r['cargando'] is False


def test_abrir_asigna_selid_tras_cargar_y_guarda_borrador_de_la_celda_anterior():
    t = open(HTML, encoding='utf-8').read()
    m = re.search(r'async function abrir\(id\)\{(.*?)\n finally\{carga\.fin\(\)\}\}', t, re.S); assert m
    c = m.group(1)
    assert c.index("await api('/api/celda?id='+id)") < c.index('selId=id;selCelda=') and 'selId=id;' not in c.split("await api('/api/celda?id='+id)")[0]
    assert c.index('guardarBorradorDe(prev,textoPrev)') < c.index("await api('/api/celda?id='+id)")        # borrador de la celda anterior antes de cambiar
    assert 'carga.vigente(tok)' in c and "bannerSesion('Error al abrir la celda" in c                          # errores visibles
    assert "'/api/borrador_borrar'" in t and "api('/api/borrador'," in t and 'await borrarBorradorDe(selCelda)' in t
