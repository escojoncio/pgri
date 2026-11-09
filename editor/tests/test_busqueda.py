import pytest
from gridania_editor import busqueda as B


def indice():
    i = B.Indice()
    datos = [(1, 'A', 'Cámara de Cristal', 'chambre', 'Visita la Cámara.', 'rojo'), (2, 'A', 'ひかり', 'lumière', 'camara de fotos', 'verde'),
             (3, 'B', 'camarada', 'camarade', 'Un camarada', 'blanco'), (4, 'B', 'x', 'y', 'CAMARA', 'naranja')]
    for id_, h, ja, fr, es, st in datos: i.anadir({'id': id_, 'hoja': h, 'row': id_, 'sub': None, 'col': 1, 'ja': ja, 'fr': fr, 'es': es, 'estado': st})
    return i


def ids(i, **kw):
    return [r['id'] for r in i.buscar(B.Consulta(**kw), 0, 50)['resultados']]


def test_subcadena_ignora_mayusculas_y_tildes():
    assert ids(indice(), texto='camara') == [1, 2, 3, 4]


def test_distinguir_tildes_y_mayusculas():
    i = indice()
    assert ids(i, texto='cámara', tildes=True, mayus=True) == []
    assert ids(i, texto='Cámara', tildes=True, mayus=True) == [1]          # JP/ES de la celda 1
    assert ids(i, texto='camara', tildes=True) == [2, 3, 4]
    assert ids(i, texto='CAMARA', mayus=True) == [4]


def test_palabra_completa_y_exacto():
    i = indice()
    assert ids(i, texto='camara', modo='palabra') == [1, 2, 4]
    assert ids(i, texto='camara de fotos', modo='exacto', campos=['es']) == [2]
    assert ids(i, texto='camara', modo='exacto', campos=['es']) == [4]


def test_campos_ja_fr_es():
    i = indice()
    assert ids(i, texto='ひかり', campos=['ja']) == [2] and ids(i, texto='lumi', campos=['fr']) == [2] and ids(i, texto='lumi', campos=['es']) == []


def test_regex_y_error():
    i = indice()
    assert ids(i, texto=r'^c\w+ra', modo='regex', campos=['es']) == [2, 4]
    with pytest.raises(ValueError): B.Consulta('(', modo='regex')
    with pytest.raises(ValueError): B.Consulta('')


def test_contadores_filtros_y_fragmento():
    r = indice().buscar(B.Consulta('camara'), 0, 2)
    assert r['total'] == 4 and r['por_hoja'] == {'A': 2, 'B': 2} and r['por_estado']['rojo'] == 1 and len(r['resultados']) == 2
    f = r['resultados'][0]['campos']['es']; assert f['t'][f['ini']:f['fin']].lower().startswith('cám')
    assert ids(indice(), texto='camara', estados=['verde']) == [2] and ids(indice(), texto='camara', hoja='B') == [3, 4]


def test_exportar_y_reemplazo_en_texto(tmp_path):
    p = tmp_path / 'x.tsv'; assert indice().exportar(B.Consulta('camara'), str(p)) == 4
    assert '[[' in p.read_text(encoding='utf-8')
    q = B.Consulta('camara')
    assert q.reemplazar('La Cámara y camara', 'sala') == ('La sala y sala', 2)
    q = B.Consulta(r'(\w+) (\w+)', modo='regex', mayus=True)
    assert q.reemplazar('uno dos', r'\2 \1') == ('dos uno', 1)


def test_actualizar_invalida_cache():
    i = indice(); i.buscar(B.Consulta('zzz', campos=['es']))
    i.actualizar(1, 'zzz', 'verde'); assert ids(i, texto='zzz', campos=['es']) == [1]
