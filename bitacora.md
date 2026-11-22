# Bitacora tecnica (pgri)

## Editor Python (editor/gridania_editor, UI web local en ventana Edge/Chrome; empaquetado PyInstaller en Actions `editor`)

### Cambios (sin commit previo, ahora en un commit)
- JA/FR sin GitHub: `repo_env.py` carga tools/py de la copia descargada (opcional) o de `gridania_editor/embebido/tools/py` (copia literal de tools/py de gridania, 548 KB, solo .py/.tsv/.txt; sin textos del juego). `aplicacion.hay_textos()`, `/api/estado` anade `textos_ok`, `textos_fuente`, `ruta_juego_detectada`. `extractor.detectar_ruta_juego()` (SE launcher/Steam). `indexer.es_mismo()`: sin ja previo no hay «nuevo». `aplicacion._calcular_novedades`: primera extraccion sin comparar. `builder.clonar` tolera origen inexistente. Textos de la UI marcan GitHub como opcional.
- Ficheros junto al .exe: `ventana.dir_perfil` ahora siempre `<datos>/perfil-ventana` (antes %LOCALAPPDATA%; CAMBIO DE CONTRATO); `config._NO_COPIAR` incluye `perfil-ventana`.
- Vista previa: nuevo `ui/vista.js` (funciones puras, servido en `/vista.js`): fuente monoespaciada, cuadro de ancho fijo en `ch` (duro 61 / creador 51), reglas en seguro/duro, macros como piezas, sin etiquetas crudas, selector fem/masc/ambas. `celda.Motor.vista` devuelve `caja.envuelve/fija/creador`; `Motor.modo_suavizado` aplica las mismas exclusiones que el .dat (excluida, narrador, caja fija) y devuelve `suavizado.motivo`.
- Espaciado masivo: `espaciado.py` (aplicar/quitar sobre todas las hojas; solo celdas verdes; Balloon y NpcYell nunca; narrador y cajas fijas no; nunca cambia palabras/macros/n. de trozos), tareas `/api/espaciado_masivo`, `/api/espaciado_deshacer`, `/api/espaciado_registros`; registros en `datos/espaciado/<fecha>_<modo>.{jsonl,resumen.json}` (5 ultimos); `aplicacion.lock_ediciones`. Botones en cabecera de `ui/index.html`.
- CI: `.github/workflows/editor.yml` anade `--add-data gridania_editor/embebido`.
- Tests: `editor/tests/test_espaciado_vista.py` (nuevo); `test_arranque2.py` y `conftest.py` adaptados (`GRIDANIA_TEST_REPO`).

### Estado de pruebas
- `pytest editor/tests`: 122 passed, 57 skipped (los skip necesitan checkout completo de gridania/juego instalado).
- SIN PROBAR: `espaciado.ejecutar/deshacer` de extremo a extremo (necesita BD indexada y textos reales); `vista.js` en Edge real (solo node, sin DOM); PyInstaller con embebido; detectar_ruta_juego en Windows real; extraccion real desde sqpack con la copia embebida.

### Pendientes
- Probar en Windows: Importar parche sin GitHub, ambos botones de espaciado con deshacer, vista de creador (51) y macros de genero.
- Resincronizar `embebido/` desde gridania (commit 75d0ad39) cuando cambie tools/py.
