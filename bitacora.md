# Bitacora tecnica (pgri)

## Editor Python (editor/gridania_editor, UI web local en ventana Edge/Chrome; empaquetado PyInstaller en Actions `editor`)

### Cambios (sin commit previo, ahora en un commit)
- JA/FR sin GitHub: `repo_env.py` carga tools/py de la copia descargada (opcional) o de `gridania_editor/embebido/tools/py` (copia literal de tools/py de gridania, 548 KB, solo .py/.tsv/.txt; sin textos del juego). `aplicacion.hay_textos()`, `/api/estado` anade `textos_ok`, `textos_fuente`, `ruta_juego_detectada`. `extractor.detectar_ruta_juego()` (SE launcher/Steam). `indexer.es_mismo()`: sin ja previo no hay «nuevo». `aplicacion._calcular_novedades`: primera extraccion sin comparar. `builder.clonar` tolera origen inexistente. Textos de la UI marcan GitHub como opcional.
- Ficheros junto al .exe: `ventana.dir_perfil` ahora siempre `<datos>/perfil-ventana` (antes %LOCALAPPDATA%; CAMBIO DE CONTRATO); `config._NO_COPIAR` incluye `perfil-ventana`.
- Vista previa: nuevo `ui/vista.js` (funciones puras, servido en `/vista.js`): fuente monoespaciada, cuadro de ancho fijo en `ch` (duro 61 / creador 51), reglas en seguro/duro, macros como piezas, sin etiquetas crudas, selector fem/masc/ambas. `celda.Motor.vista` devuelve `caja.envuelve/fija/creador`; `Motor.modo_suavizado` aplica las mismas exclusiones que el .dat (excluida, narrador, caja fija) y devuelve `suavizado.motivo`.
- Espaciado masivo: `espaciado.py` (aplicar/quitar sobre todas las hojas; solo celdas verdes; Balloon y NpcYell nunca; narrador y cajas fijas no; nunca cambia palabras/macros/n. de trozos), tareas `/api/espaciado_masivo`, `/api/espaciado_deshacer`, `/api/espaciado_registros`; registros en `datos/espaciado/<fecha>_<modo>.{jsonl,resumen.json}` (5 ultimos); `aplicacion.lock_ediciones`. Botones en cabecera de `ui/index.html`.
- CI: `.github/workflows/editor.yml` anade `--add-data gridania_editor/embebido`.
- Tests: `editor/tests/test_espaciado_vista.py` (nuevo); `test_arranque2.py` y `conftest.py` adaptados (`GRIDANIA_TEST_REPO`).

### Correcciones tras revision adversarial (ciclo 1)
- `espaciado.espaciar_celda` (aplicar): ya no es reflujo global; reproduce `--solo-incumplen` (violaciones antes == 0 -> ya_cumplia; descarta si violaciones no bajan o el coste empeora -> categoria nueva `sin_mejora`). El boton de una celda (celda.py) no cambia. CAMBIO DE COMPORTAMIENTO: «aplicar» toca menos celdas.
- `celda.Motor.vista`: n=0 (sin limite de lineas por ventana) tambien para `descripcion`, Lobby y CharaMake*; `vista.js` no avisa de >4 lineas si `caja.creador` o tipo descripcion.
- `espaciado.ultimo_registro`: acepta `en_curso` si el .jsonl tiene filas; `ejecutar` actualiza `cambiadas` del resumen tras cada hoja (deshacer tras cuelgue).
- `aplicacion.py`: todos los escritores de ediciones (guardar_lote/restaurar_lote/guardar) bajo `lock_ediciones`.
- Docstring y dialogos de espaciado corregidos: en «aplicar» las cajas fijas SI se reflujan (49); «quitar» no las toca.
- `/api/estado`: `detectar_ruta_juego` cacheado por sesion (`Aplicacion._ruta_detectada`).
- Tests nuevos (SQLite temporal + Motor falso, NO el motor real): ejecutar->deshacer restaura es/es_json/origen/h_es/editada y fila de ediciones; guardado concurrente; en_curso; n=0 creador; filtro solo-incumplen.

### Correcciones tras revision adversarial (ciclo 2)
- `espaciado.ejecutar`: en `aplicar` fija `RL.MARGEN = 0.0` (como `--solo-incumplen`) y lo restaura en `finally`; `ya_correcta` con violaciones > 0 se etiqueta `sin_mejora` (no `ya_cumplia`).
- Textos (docstring, title de bEspAp, ayuda, confirmacion): aplicar solo reflujan quest* (58), DefaultTalk (58) y Lobby (49); sistema, descripciones y CharaMake no se tocan.
- `celda.Motor.lineas_ventana(pf, hoja)` (nuevo, estatico): n lineas por ventana de la vista (0 = sin limite); test de comportamiento en lugar de buscar texto en el fuente.

### Estado de pruebas
- `pytest editor/tests`: 127 passed, 57 skipped (los skip necesitan checkout completo de gridania/juego instalado).
- SIN PROBAR: `espaciado.ejecutar/deshacer` de extremo a extremo (necesita BD indexada y textos reales); `vista.js` en Edge real (solo node, sin DOM); PyInstaller con embebido; detectar_ruta_juego en Windows real; extraccion real desde sqpack con la copia embebida.

### Generar .dat sin suavizado automatico (2026-11-23)
- CAMBIO DE COMPORTAMIENTO: `builder.generar(..., suavizar=False)` y `preparar_stage(..., suavizar=False)` ya NO ejecutan `SS.procesar_hoja` (suavizado de saltos) al generar; el `.dat` lleva exactamente el texto guardado en el editor (repo + ediciones). `tarea_generar` / `/api/generar` aceptan `suavizar` (por defecto False). El espaciado se aplica antes con los botones de espaciado masivo / suavizar. La validacion del blob (`validar_blob_suavizado`) es estructural y sigue pasando sin suavizado.
- Ficheros: `builder.py`, `aplicacion.py`, `servidor.py`, `ui/index.html` (textos de ayuda), `celda.py` (comentario). Tests: 127 passed, 57 skipped. SIN PROBAR: generacion real del .dat con juego instalado.
- Consecuencia: objetivos/menus/descripciones que antes se espaciaban solo al generar ya no lo hacen; si hace falta, aplicar el espaciado masivo antes de generar.

### Limitacion conocida (revision adversarial pase 3, gravedad baja)
- `RL.MARGEN` y `RL.CFG.*` son globales del modulo de reflujo: si se pulsa «Suavizar saltos» de una celda mientras corre «aplicar espaciado», esa vista previa usa `MARGEN=0.0` (algo mas agresivo) hasta que acaba la tarea. Transitorio, no corrompe datos; misma carrera que ya existia con `RL.CFG` en `celda.py`. `base.ocupar` no sirve (`espaciado.ejecutar` llama a `exigir_libre`); arreglo limpio: pasar margen/cfg por parametro a `procesar_celda`.

### Pendientes
- Probar en Windows: Importar parche sin GitHub, ambos botones de espaciado con deshacer, vista de creador (51) y macros de genero.
- Resincronizar `embebido/` desde gridania (commit 75d0ad39) cuando cambie tools/py.

## 2026-11-23: textos de ayuda del editor
- `ui/index.html` (tooltip `bGen`, ayuda «Generar translations.dat», «Suavizado») y `ui/vista.js` (`MOTIVOS`/estado «aplicado»): ya NO dicen que generar el .dat aplica suavizado; `builder.generar(suavizar=False)` es el comportamiento real. Tests `test_espaciado_vista.py` 11 OK. Sin recompilar el exe: hace falta nueva build en Actions para ver el cambio.

## 2026-11-23: boton «Traducir con Gemini» (PRUEBA, sin probar en Windows real)
- `ventana.lanzar_ia(home)` (nuevo): mini ventana Edge/Chrome `--app=https://gemini.google.com/app`, 540x860, perfil `<datos>/perfil-ia` (conserva sesion de Google); NO usa el navegador predeterminado (sin Edge/Chrome -> error en la UI). No participa en latido/cierre del editor. `Aplicacion.abrir_ia`, ruta `POST /api/abrir_ia` (`servidor.py`).
- `ui/index.html` (fila de botones del ES): `bIA` copia «Traduce esto al castellano:\n\n» + texto JA o FR de la celda (`iaFuente`) y abre la ventana; `bIAPegar` pega el portapapeles en `#es` y dispara `input` (previa). Flujo manual: Ctrl+V en Gemini, copiar respuesta, «Pegar respuesta», revisar, Guardar.
- Tests: `editor/tests/test_ventana_ia.py` (2 OK, popen falso). SIN PROBAR: ventana real de Gemini, `navigator.clipboard.readText` en la ventana Edge (puede pedir permiso), build PyInstaller.
- Pendiente: si la prueba gusta, lotes (varias celdas por prompt) y pegado que reparta por celdas.

### 2026-11-23 (2): Gemini escribe y envia el prompt solo
- Antes el boton solo copiaba al portapapeles y habia que pegar a mano (no era lo pedido). Ahora `ia_cdp.py` (nuevo, stdlib): cliente WebSocket minimo + CDP; `ventana.lanzar_ia(..., puerto=)` anade `--remote-debugging-port=<libre>` y `--remote-allow-origins=*` (solo 127.0.0.1, abierto mientras vive la ventana de Gemini). `Aplicacion.abrir_ia(texto, enviar=True)` lanza (o reutiliza `self._ia` si el puerto responde, navegando a chat nuevo) y en un hilo hace `ia_cdp.escribir_y_enviar`: espera el cuadro (`rich-textarea .ql-editor` / `div[role=textbox][contenteditable]`), `Input.insertText`, clic en `button.send-button` (o Enter). `POST /api/abrir_ia {texto}`; el prompt sigue copiandose al portapapeles como respaldo.
- Tests: `test_ventana_ia.py` 3 OK (CDP falso). SIN PROBAR en Windows real: selectores del DOM de Gemini (pueden cambiar), sesion de Google no iniciada (tras timeout 60 s queda solo el portapapeles; revisar `datos/editor.log`, lineas `IA:`).
