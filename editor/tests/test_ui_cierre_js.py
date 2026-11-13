"""Logica JS de cierre (beforeunload / pagehide / pageshow) extraida de ui/index.html (entre /*LOGICA_INI*/ y /*LOGICA_FIN*/) y ejecutada con node."""
import os, re, shutil, subprocess, pytest

HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gridania_editor', 'ui', 'index.html')
MOD = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gridania_editor', 'ui', 'borradores.js'))
NODE = shutil.which('node')


def _logica():
    t = open(HTML, encoding='utf-8').read()
    m = re.search(r'/\*LOGICA_INI\*/(.*?)/\*LOGICA_FIN\*/', t, re.S); assert m; return m.group(1)


def _node(js, tmp_path):
    pre = "const {claveCelda,decidirBorrador,puedeEnviarBorrador,crearCarga}=require(%r);\n" % MOD
    f = tmp_path / 't.js'; f.write_text(pre + _logica() + '\n' + js, encoding='utf-8')
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
    for ruta in (str(f), MOD):
        r = subprocess.run([NODE, '--check', ruta], capture_output=True, text=True); assert r.returncode == 0, r.stderr
    assert '<script src="/borradores.js"></script>' in t


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
