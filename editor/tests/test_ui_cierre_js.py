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
