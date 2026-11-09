"""Lanzador del .exe (PyInstaller)."""
import multiprocessing, sys
if __name__ == '__main__':
    multiprocessing.freeze_support()
    from gridania_editor.app import main
    sys.exit(main())
