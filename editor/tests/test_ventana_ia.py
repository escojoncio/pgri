from gridania_editor import ventana


def test_lanzar_ia_usa_perfil_propio_y_ventana_pequena(tmp_path):
    llamadas = []
    class P:
        pid = 1
    p = ventana.lanzar_ia(str(tmp_path), buscar=lambda: 'msedge.exe', popen=lambda cmd, **kw: (llamadas.append(cmd), P())[1])
    assert p is not None
    cmd = llamadas[0]
    assert '--app=' + ventana.URL_IA in cmd
    assert '--user-data-dir=%s' % (tmp_path / 'perfil-ia') in cmd
    assert '--window-size=540,860' in cmd
    assert (tmp_path / 'perfil-ia').is_dir()


def test_lanzar_ia_sin_navegador_no_abre_nada(tmp_path):
    assert ventana.lanzar_ia(str(tmp_path), buscar=lambda: None, popen=lambda *a, **k: 1 / 0) is None
