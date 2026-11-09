"""Punto de entrada: servidor local + ventana propia (pywebview/WebView2) o, si no esta disponible, el navegador por defecto."""
import argparse, sys, threading, webbrowser
from . import stdlib_para_scripts  # noqa: F401  (declara la stdlib que usan los scripts descargados)
from .aplicacion import Aplicacion
from .servidor import Servidor


def main(argv=None):
    ap = argparse.ArgumentParser(description='Editor de traducciones Gridania')
    ap.add_argument('--navegador', action='store_true', help='usar el navegador por defecto en vez de la ventana propia')
    ap.add_argument('--puerto', type=int, default=0); ap.add_argument('--carpeta', help='carpeta de trabajo (por defecto %%LOCALAPPDATA%%/GridaniaEditor)')
    ap.add_argument('--sin-abrir', action='store_true', help='solo arranca el servidor (pruebas)')
    a = ap.parse_args(argv)
    app = Aplicacion(a.carpeta); srv = Servidor(app, a.puerto); srv.arrancar()
    url = srv.url
    print('Editor Gridania en', url, flush=True)
    if a.sin_abrir:
        srv.salir.wait(); srv.parar(); return 0
    usado = False
    if not a.navegador:
        try:
            import webview
            win = webview.create_window('Editor de traducciones Gridania', url, width=1400, height=900)
            threading.Thread(target=lambda: (srv.salir.wait(), win.destroy()), daemon=True).start()
            webview.start()
            usado = True
        except Exception as x:
            print('ventana propia no disponible (%s: %s); se usa el navegador' % (type(x).__name__, x), flush=True)
    if not usado:
        webbrowser.open(url)
        try: srv.salir.wait()
        except KeyboardInterrupt: pass
    srv.parar(); return 0


if __name__ == '__main__':
    sys.exit(main())
