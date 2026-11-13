"""Logica REAL de borradores (ui/borradores.js, sin DOM) ejecutada con node: guardar/borrar/cola/resolver/decisiones, con un servidor falso en memoria."""
import json, os, shutil, subprocess, pytest

MOD = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gridania_editor', 'ui', 'borradores.js'))
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(not NODE, reason='sin node')

PRE = '''
const B=require(%r);
const C={id:7,hoja:'Quest',row:3,sub:null,col:1,h:'h1',base:'viejo'};
function mk(opt){opt=opt||{};const srv={};const log=[];let espera=null;
 const api=async(ruta,b)=>{log.push(ruta+':'+(b.texto===undefined?'':b.texto)+(b.ver?'#'+b.ver:''));
  if(opt.retardo&&ruta==='/api/borrador'){await new Promise(r=>opt.retardo.push(r))}
  const k=[b.hoja,b.row,b.sub==null?'':b.sub,b.col].join('|')+(b.ver?'#'+b.ver:'');
  if(ruta==='/api/borrador')srv[k]=b;else if(ruta==='/api/borrador_borrar')delete srv[k];return {ok:true}};
 const dlg=[];
 const G=B.crearGestor({api,mostrar:(b,d)=>{dlg.push('abre');return new Promise(r=>{dlg.push(r)}).then(x=>{dlg.push('cierra');return x})},normalizar:opt.normalizar||(async(c,t)=>t.trim()),cambio(){}});
 return {G,srv,log,dlg}}
''' % MOD


def _node(js, tmp_path):
    f = tmp_path / 't.js'; f.write_text(PRE + '(async()=>{\n' + js + '\n})().catch(e=>{console.error(e);process.exit(1)});', encoding='utf-8')
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=20); assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_1_texto_igual_a_la_base_borra_el_borrador_del_servidor(tmp_path):
    r = _node('''
const {G,srv}=mk();const st=t=>({cargando:false,celda:C,texto:t,base:'viejo'});
await G.tick(st('nuevo'));const a=Object.keys(srv).length;
await G.tick(st('viejo'));const b=Object.keys(srv).length;      // el usuario deshizo el cambio
await G.tick(st('nuevo2'));const c=Object.keys(srv).length;
await G.alSalir(C,'viejo','viejo');const d=Object.keys(srv).length;   // cambia de celda con texto igual a la base
// y al cambiar de celda con texto distinto se guarda
await G.alSalir(C,'otro','viejo');const e=Object.keys(srv).length;
await G.alSalir(C,'viejo','viejo');const f=Object.keys(srv).length;
console.log(JSON.stringify([a,b,c,d,e,f]));''', tmp_path)
    assert r == [1, 0, 1, 0, 1, 0]


def test_2b_decidir_luego_y_luego_editar_archiva_el_antiguo(tmp_path):
    r = _node('''
const {G,srv,dlg}=mk();
G.cargar([{hoja:'Quest',row:3,sub:null,col:1,h:'h0',texto:'ANTIGUO',base:'otra',fecha:1}]);
const msgs=[];
const p=G.resolver(C,{h:'h1',es_texto:'viejo'},{vigente:()=>true,poner(){},msg:m=>msgs.push(m)});
await new Promise(r=>setTimeout(r,5));dlg[1]('luego');await p;            // «Decidir luego»
await G.tick({cargando:false,celda:C,texto:'viejo',base:'viejo'});          // texto == base: NO borra el pendiente
const tras_tick=Object.values(srv).map(x=>x.texto);
await G.tick({cargando:false,celda:Object.assign({},C),texto:'nuevo',base:'viejo'});   // edita: el antiguo se conserva
const k=Object.keys(srv).sort();
console.log(JSON.stringify({tras_tick,k,textos:k.map(x=>srv[x].texto),msgs}));''', tmp_path)
    assert r['tras_tick'] == []
    assert r['k'] == ['Quest|3||1', 'Quest|3||1#a1'] and r['textos'] == ['nuevo', 'ANTIGUO']
    assert 'pendiente de decidir' in r['msgs'][0]


def test_2c_decidir_luego_no_se_borra_con_texto_igual_a_la_base(tmp_path):
    r = _node('''
const {G,srv,dlg}=mk();
// el servidor ya lo tenia (cargar solo llena el cliente): simulamos con un guardado real
await G.guardarBorradorDe(C,'PEND');
const p=G.resolver(C,{h:'h9',es_texto:'otro'},{vigente:()=>true,poner(){},msg(){}});
await new Promise(r=>setTimeout(r,5));dlg[1]('luego');await p;
await G.tick({cargando:false,celda:C,texto:'otro',base:'otro'});
await G.alSalir(C,'otro','otro');
console.log(JSON.stringify(Object.values(srv).map(x=>x.texto)));''', tmp_path)
    assert r == ['PEND']


def test_3_borrar_espera_al_post_en_vuelo_y_no_resucita(tmp_path):
    r = _node('''
const retardo=[];const {G,srv,log}=mk({retardo});
const post=G.guardarBorradorDe(C,'en vuelo');       // POST colgado
await new Promise(r=>setTimeout(r,2));
const del=G.borrarBorradorDe(C);                    // se encola detras
await new Promise(r=>setTimeout(r,2));
const antes=Object.keys(srv).length;
retardo.shift()();await post;await del;             // el POST termina y entonces se borra
console.log(JSON.stringify({antes,despues:Object.keys(srv).length,log}));''', tmp_path)
    assert r['antes'] == 0 and r['despues'] == 0 and r['log'] == ['/api/borrador:en vuelo', '/api/borrador_borrar:']


def test_3b_un_post_encolado_antes_de_borrar_se_cancela(tmp_path):
    r = _node('''
const retardo=[];const {G,srv,log}=mk({retardo});
const p1=G.guardarBorradorDe(C,'uno');await new Promise(r=>setTimeout(r,2));
const p2=G.guardarBorradorDe(C,'dos');              // encolado tras uno
const del=G.borrarBorradorDe(C);                    // lo anula
retardo.shift()();await p1;await p2;await del;
console.log(JSON.stringify({srv:Object.keys(srv).length,log}));''', tmp_path)
    assert r['srv'] == 0 and r['log'] == ['/api/borrador:uno', '/api/borrador_borrar:']


def test_3c_texto_normalizado_al_guardar_no_da_conflicto_espurio(tmp_path):
    r = _node('''
const {G,srv,dlg}=mk();
// el borrador quedo con el texto sin normalizar («hola  » -> guardado «hola»)
G.cargar([{hoja:'Quest',row:3,sub:null,col:1,h:'h1',texto:'hola  ',base:'viejo',fecha:1}]);
await G.resolver(C,{h:'h1',es_texto:'hola'},{vigente:()=>true,poner(){throw new Error('no debe restaurar')},msg(){}});
console.log(JSON.stringify({dialogos:dlg.length,quedan:G.tiene('Quest|3||1')}));''', tmp_path)
    assert r == {'dialogos': 0, 'quedan': False}


def test_4_pedir_decision_con_dialogo_abierto_encola(tmp_path):
    r = _node('''
const {G,dlg}=mk();const orden=[];
const a=G.pedirDecision({h:'1',texto:'a'},{h:'1',es_texto:'x'}).then(x=>orden.push('a:'+x));
const b=G.pedirDecision({h:'1',texto:'b'},{h:'1',es_texto:'x'}).then(x=>orden.push('b:'+x));
await new Promise(r=>setTimeout(r,5));
const abiertos1=dlg.filter(x=>x==='abre').length;     // solo uno abierto
dlg[1]('borrador');await a;await new Promise(r=>setTimeout(r,5));
const abiertos2=dlg.filter(x=>x==='abre').length;
dlg.filter(x=>typeof x==='function')[1]('actual');await b;
// una decision obsoleta (otra carga ya vigente) no abre dialogo
let vig=true;const c=G.pedirDecision({h:'1',texto:'c'},{h:'1',es_texto:'x'},()=>vig);
vig=false;
console.log(JSON.stringify({orden,abiertos1,abiertos2,c:await c}));''', tmp_path)
    assert r == {'orden': ['a:borrador', 'b:actual'], 'abiertos1': 1, 'abiertos2': 2, 'c': 'luego'}


def test_resolver_aplicar_conflicto_y_guardar_archiva_pendiente(tmp_path):
    r = _node('''
const {G,srv,dlg}=mk();const puesto=[];
G.cargar([{hoja:'Quest',row:3,sub:null,col:1,h:'h1',texto:'nuevo',base:'viejo',fecha:5}]);
await G.resolver(C,{h:'h1',es_texto:'viejo'},{vigente:()=>true,poner:(t,m)=>puesto.push(t),msg(){}});   // aplicar
// pendiente + guardar con otro texto: se archiva, no se pierde
await G.guardarBorradorDe(C,'P');
const p=G.resolver(C,{h:'h2',es_texto:'zzz'},{vigente:()=>true,poner(){},msg(){}});
await new Promise(r=>setTimeout(r,5));dlg[1]('luego');await p;
await G.borrarBorradorDe(C,'',{archivarSi:'guardado'});
console.log(JSON.stringify({puesto,k:Object.keys(srv),t:Object.values(srv).map(x=>x.texto)}));''', tmp_path)
    assert r['puesto'] == ['nuevo'] and r['k'] == ['Quest|3||1#a1'] and r['t'] == ['P']
