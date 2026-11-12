import json, os
import pytest
from gridania_editor import clases, flujo, indexer


def test_clases_mapeo():
    c = clases.clase_de
    assert c('ENpcResident') == c('DefaultTalk') == c('Balloon') == c('NpcYell') == c('CustomTalk') == 'Dialogo de PNJ'
    assert c('quest/000/ManFst002_00085') == c('Quest') == c('Journal') == 'Misiones'
    assert c('cut_scene/022/x') == 'Escenas'
    assert c('Item') == c('EventItem') == 'Objetos'
    assert c('Action') == 'Habilidades y acciones'
    assert c('PlaceName') == 'Lugares'
    assert c('Addon') == c('Lobby') == c('LogMessage') == 'Interfaz'
    assert c('Achievement') == c('Leve') == 'Logros, levis y otros'
    assert c('HojaInventadaXYZ') == clases.OTROS == 'Otros'
    assert clases.OTROS in clases.CLASES


def test_flujo_persistencia_y_tsv(tmp_path):
    f = flujo.Flujo(str(tmp_path / 'flujo.json'))
    assert f.estado('Item', 1, None, 2) == 'sin'
    assert f.poner([('Item', 1, None, 2), ('quest/000/a', 3, 4, 1)], 'hecho') == 2
    assert f.poner([('Item', 1, None, 2)], 'por_hacer') == 1
    assert f.totales() == {'por_hacer': 1, 'hecho': 1}
    g = flujo.Flujo(str(tmp_path / 'flujo.json'))          # persiste
    assert g.estado('Item', 1, None, 2) == 'por_hacer' and g.estado('quest/000/a', 3, 4, 1) == 'hecho'
    ruta = str(tmp_path / 'e.tsv'); assert g.exportar_tsv(ruta) == 2
    h = flujo.Flujo(str(tmp_path / 'otro.json')); assert h.importar_tsv(ruta) == (2, 0)
    assert h.datos == g.datos
    assert h.importar_texto('hoja\trow\tsub\tcol\testado\nItem\t1\t\t2\tsin\nmal\tx\t\t1\thecho\n') == (1, 1)
    assert h.estado('Item', 1, None, 2) == 'sin'
    with pytest.raises(ValueError): g.poner([('Item', 1, None, 2)], 'raro')


@pytest.fixture()
def base(tmp_path):
    b = indexer.Base(str(tmp_path / 'x.db'))
    f = flujo.Flujo(str(tmp_path / 'flujo.json')); b.registrar_flujo(f.estado_sql)
    filas = [('quest/000/a', 1, None, 1, 'rojo', 'h', 'ja uno', '', 'es uno', None, None, None, 0),
             ('quest/000/a', 2, None, 1, 'verde', 'h', 'ja dos', '', 'es dos', None, None, None, 0),
             ('ENpcResident', 1, None, 0, 'rojo', 'h', 'ja tres', '', '', None, None, None, 0),
             ('Item', 1, 0, 0, 'verde', 'h', 'ja cuatro', '', 'es cuatro', None, None, None, 1)]
    b.con.executemany('INSERT INTO celdas(hoja,row,sub,col,estado,h,ja,fr,es,es_json,origen,h_es,editada) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', filas); b.con.commit()
    return b, f


def test_filtros_clase_flujo_y_combinados(base):
    b, f = base
    assert indexer.listar(b, clase='Misiones')[0] == 2
    assert indexer.listar(b, clase='Dialogo de PNJ')[0] == 1
    assert indexer.listar(b, clase='Misiones', estados=['rojo'])[0] == 1
    assert indexer.listar(b, clase='Misiones', q='dos')[0] == 1
    f.poner([('quest/000/a', 2, None, 1)], 'hecho'); f.poner([('Item', 1, 0, 0)], 'por_hacer')
    assert indexer.listar(b, flujo='hecho')[0] == 1 and indexer.listar(b, flujo='por_hacer')[0] == 1 and indexer.listar(b, flujo='sin')[0] == 2
    assert indexer.contadores_flujo(b) == {'por_hacer': 1, 'hecho': 1, 'sin': 2}
    assert indexer.contadores_flujo(b, clase='Misiones') == {'por_hacer': 0, 'hecho': 1, 'sin': 1}
    cc = indexer.contadores_clase(b)
    assert cc['Misiones'] == 2 and cc['Objetos'] == 1 and sum(cc.values()) == 4
    assert len(indexer.celdas_filtradas(b, clase='Misiones', flujo='hecho')) == 1
    _, filas = indexer.listar(b, hoja='Item'); assert filas[0]['clase'] == 'Objetos' and filas[0]['flujo'] == 'por_hacer'


def test_busqueda_con_clase_y_flujo(base):
    from gridania_editor import busqueda
    b, f = base; i = busqueda.Indice.desde_base(b); i.flujo = f
    f.poner([('quest/000/a', 1, None, 1)], 'hecho')
    assert i.buscar(busqueda.Consulta('ja', ['ja'], clase='Misiones'))['total'] == 2
    assert i.buscar(busqueda.Consulta('ja', ['ja'], clase='Misiones', flujo='hecho'))['total'] == 1
    assert i.buscar(busqueda.Consulta('ja', ['ja'], clase='Objetos', flujo='hecho'))['total'] == 0
    assert i.buscar(busqueda.Consulta('ja', ['ja'], clase='Objetos'))['resultados'][0]['clase'] == 'Objetos'
