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
