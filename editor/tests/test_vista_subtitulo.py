"""La vista ingame de un subtitulo usa el tope por celda relativo al frances (min(90, max(fr_ancho, 58))), no el 58 base del perfil: si no, la UI marcaba LINEA_EXCEDE."""

from conftest import REPO, necesita_repo

HOJA = 'cut_scene/022/VoiceMan_02200'


@necesita_repo
def test_subtitulo_cut_scene_usa_tope_relativo_al_fr(R):
    from gridania_editor import celda
    m = celda.Motor(R, REPO, REPO, None)
    c = m.contexto(HOJA, 7, None, 1)
    assert c.pf.tipo == 'subtitulo'
    es = ['Me llamo Yugiri. Venimos de Doma,', 'ciudad fronteriza del pequeño continente de Othard,', 'y hemos cruzado el mar huyendo.']
    r = m.evaluar(c, m.es_a_texto(c, es))
    caja = r['vista']['caja']
    assert caja['duro'] == caja['seguro'] == R.NC.tope_ancho_subtitulo(c.pf, R.NC.medida_fr(c.fr_text, c.pf)) > 58
    # ninguna linea de la vista (la que pinta la UI con v.caja.duro) excede el tope
    anchos = [len(l.replace('\x01', '').replace('\x02', '')) for w in r['vista']['ventanas'] for l in w]
    assert max(anchos) <= caja['duro']
    assert not [a for a in r['avisos'] if a[0].startswith('CAJA_')]


@necesita_repo
def test_lineas_de_la_vista_son_las_del_suavizado_del_dat(R):
    """«2 lineas» con 3 en el texto: la vista muestra lo que saldra en el .dat (suavizado une saltos a media frase); mismo origen que el 58 falso"""
    from gridania_editor import celda
    m = celda.Motor(R, REPO, REPO, None)
    c = m.contexto(HOJA, 7, None, 1)
    es = ['Me llamo Yugiri. Venimos de Doma,', 'ciudad fronteriza del pequeño continente de Othard,', 'y hemos cruzado el mar huyendo.']
    r = m.evaluar(c, m.es_a_texto(c, es))
    assert r['texto'].count('\n') == 2 and r['suavizado']['suavizado'] == 'aplicado'
    assert r['vista']['nlineas'] == 2 and r['vista']['caja']['duro'] == R.NC.tope_ancho_subtitulo(c.pf, R.NC.medida_fr(c.fr_text, c.pf))
