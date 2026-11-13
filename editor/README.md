# Editor de traducciones Gridania (Windows)

Programa de escritorio (carpeta `GridaniaEditor/` con `GridaniaEditor.exe`) para editar cualquier texto del juego en tu PC. Python 3 + los scripts de `tools/py` del repo
(se descargan al importar; el `.exe` NO lleva textos del juego ni del repo) + interfaz local en ventana propia: la ventana usa Microsoft Edge en modo aplicacion (`msedge.exe --app=...`, o Chrome); no hace falta instalar nada. Sin Edge ni Chrome abre el navegador predeterminado.

## Obtener el .exe
GitHub > Actions > workflow **editor** > ultima ejecucion > artefacto `GridaniaEditor-win64` (se genera en `windows-latest` con PyInstaller).
Se descarga la carpeta (`--onedir`): descomprimela y ejecuta `GridaniaEditor.exe`. Edge viene con Windows 10/11. Ayuda > Abrir en el navegador, o `GridaniaEditor.exe --navegador`, usa el navegador predeterminado. El perfil de la ventana (solo cache/cookies del navegador, NO son datos del usuario; se puede borrar) vive en `%LOCALAPPDATA%\GridaniaEditor\perfil-ventana` (o `datos/perfil-ventana` si no hay LOCALAPPDATA).

## Datos
Todo lo que genera el editor (editor.db, editor.log, faulthandler.log, config.json, flujo.json, ediciones/, exportado/, cache del repo descargado, instancia.*)
vive en la carpeta `datos/` JUNTO al ejecutable (en desarrollo `tools/editor/datos`; se puede forzar con la variable `GRIDANIA_EDITOR_HOME` o `--carpeta`).
Si esa carpeta no es escribible se avisa y se usa `Documentos/GridaniaEditor`. Al primer arranque, si `datos/` esta vacia y existe la ubicacion antigua
(`%LOCALAPPDATA%\GridaniaEditor`) se COPIAN (sin borrar) sus ajustes, ediciones y marcas; el indice, la cache del repo y la extraccion del juego no se copian
(se regeneran: Actualizar desde GitHub / Reindexar). No incluyas `datos/` al repartir el programa (contiene el token). Menu Ayuda > Abrir carpeta de datos y registros.

## Diagnostico de arranque
`datos/editor.log` registra inicio y fin de cada fase (aplicacion, servidor, busqueda de Edge/Chrome, linea de comandos y pid de la ventana, primera peticion de la UI, migracion,
vigencia, resultado y codigo de salida de la ventana) y, mientras algo tarde, un volcado cada 10 s con la etapa y las fases activas; `datos/faulthandler.log` vuelca las pilas de todos los hilos cada 30 s hasta que la UI carga.
Si la UI no pide la pagina en 30 s se abre el navegador por defecto con la URL (el servidor sigue activo).
**Cierre de la ventana por latido** (el pid de Edge no es fiable: el lanzador puede delegar y salir, o Edge seguir en segundo plano): la UI envia `/api/latido` cada 5 s y `sendBeacon('/api/cierre?k=<clave>')` al descargarse la pagina. El servidor cierra cuando (a) llega `/api/cierre` y pasan 10 s sin latido ni `GET /` (F5 no cierra), o (b) pasan >= 180 s sin latido (ventana oculta/minimizada: throttling) y el perfil de la ventana esta libre (Windows: `lockfile`; sin esa comprobacion, 300 s). Nunca cierra solo porque el proceso lanzado termine. En el navegador de respaldo (pestana normal) NO hay cierre automatico: usa el boton Salir (la UI lo avisa).

## Uso
1. **Ajustes**: repo (`escojoncio/gridania`), rama, token personal de GitHub con lectura de *Contents* (se guarda solo en
   `<carpeta del programa>\datos\config.json`; nunca en el repo ni en logs), carpeta `sqpack/ffxiv` del juego y carpeta de destino del `.dat`.
2. **Actualizar desde GitHub**: baja `traducciones/`, `data/`, `textos/ja`, `textos/fr`, `tools/py` y unas tablas de `trabajo/informes`
   (API de GitHub, sin git; la primera vez usa el zip del commit, luego solo lo que cambia por sha). Reindexa.
3. **Importar parche** (boton antes «Extraer del juego»; tras una actualizacion del juego): extrae ja y fr con `tools/py/extract_ja.py` a `datos/juego/_extrayendo` y,
   solo si termina bien, lo cambia de forma atomica por `datos/juego/textos` (la anterior se mueve a `datos/copias/<fecha>_<version>/`, se conservan las 3 ultimas; si algo
   falla `textos/` queda intacto). La version del juego (`ffxivgame.ver`) queda en `datos/juego/info.json`. Calcula el informe de novedades
   (`datos/parches/<version>.json`): **nuevas**, **cambiadas** (el es se conserva; naranja), **borradas** (con su es) y **movidas** (mismo ja que una borrada de la misma hoja:
   se propone arrastrar la traduccion, solo con Aceptar). Nuevas y cambiadas pasan a «Por hacer» con etiqueta de version (`flujo_parche.json`). Ninguna parte de la
   importacion escribe `traducciones/`, `ediciones/` ni el `es`. Flujo: **Importar parche → Novedades → traducir → Exportar cambios**.
   La clasificacion por color compara el hash `h` de la traduccion con el del japones nuevo:
   **ROJO** nueva o con japones cambiado y sin traduccion vigente; **NARANJA** japones cambiado con traduccion antigua conservada (revisar);
   **VERDE** traducida con hash vigente; **BLANCO** ya existia pero sin traducir. Sin extraccion se compara contra el japones del repo.
   API: `GET /api/parches`, `/api/parche?version&tipo&q`, `/api/parche_hoja?version&hoja&filtro`, `/api/parche_movidas?version&hoja`; `POST /api/parche_importar` (= `/api/extraer`), `/api/parche_arrastrar {version,hoja?,destinos?}`.
4. **Tabla** (izquierda): contadores por estado (clic para filtrar), filtro por hoja, busqueda de texto, solo editadas.
5. **Editor** (derecha): tres paneles JP | FR | ES con las macros resueltas (colores, saltos, genero) y filas anterior/siguiente + hablante.
   Vista previa en tiempo real «como en el juego»: reflujo automatico (`reflujar_lineas`, 58 car., maximo 4 lineas por ventana), suavizado
   de saltos (`suavizar_saltos`), perfil de caja y avisos: ventana huerfana, linea excedida, macro rota (rechazo de `construir_dat`),
   latinismos, signos japoneses o `…` (se corrigen solos), simbologia, `/say`, glosario. Se guarda con **Ctrl+S** solo si no hay errores
   criticos (mismas reglas que el hook); la fila se escribe en `ediciones/` con `origen: sesion`, `estado: traducida` y `h` correcto.
   En celdas simples cada salto de linea del cuadro de texto es un `<NewLine>` del original (el numero debe coincidir).
6. **Buscar global**: JP, FR y ES a la vez (seleccionable), todas las hojas; modos subcadena / texto exacto / palabra completa / regex;
   distinguir mayusculas y tildes; contadores total, por estado y por hoja; fragmento resaltado; clic abre la celda; **Exportar lista** (TSV).
   **Reemplazar en ES** sobre los resultados marcados (o todos), con vista previa antes/despues y las mismas validaciones al guardar
   (las celdas que no pasan se listan como rechazadas). La busqueda recorre SQLite en streaming (no carga las filas en RAM).
7. **Generar translations.dat**: fusiona repo + tus ediciones, aplica el suavizado, ejecuta `construir_dat` con la puerta
   (>= 757.594 entradas, <= 43 rechazos, 0 `…`; los dos primeros pasan a aviso si la version del juego difiere de `data/recommended-game-version.txt`)
   y `validar_blob_suavizado` (en serie). Deja `translations.dat` + `rechazos.csv` en la carpeta elegida y muestra entradas, rechazos, tamano y sha256.
   Es lento (decenas de minutos; no se ejecuta en paralelo en Windows).
8. **Exportar cambios**: copia tus ediciones (jsonl por hoja, mismas rutas que `traducciones/`) a `cambios_<fecha>/` para subirlas al repo
   (la subida por API queda para mas adelante).

## Funciones de la interfaz (resumen; dentro del programa, boton **Ayuda** y tooltips en cada control)
- **Vista «como en el juego»**: ventana oscura con borde, hablante `(-Nombre-)` como etiqueta, colores del juego, `▼` de continuar (`■` en la ultima), ventana N/M, lineas y ancho por linea (`usados/seguros`; amarillo = pasa del recomendado, rojo = supera el duro), `↵` discreto por salto. Avisa de mas de 4 lineas por ventana, linea mas ancha que la caja y ventana final huerfana. Indica si la celda se **suavizo** o **ya cumplia**.
- **♀/♂ automatico**: si el ES lleva `<Gender>...<GenderElse>...<GenderEnd>` se ven las dos variantes a la vez; sin macro, una vista. (`/api/preview` devuelve `variantes` = `{fem, masc}` o `null`; `vista` sigue siendo la del genero pedido, por compatibilidad.)
- **Clase de texto** (`gridania_editor/clases.py`, unico sitio del mapeo; `Otros` por defecto): filtro en la tabla, la busqueda global y la lista de misiones.
- **Estado de trabajo Por hacer / Hecho / Sin clasificar** (independiente del color): por celda (Alt+1/2/0), en bloque sobre los resultados filtrados (tabla o busqueda), filtro y contadores. Se guarda en `flujo.json` de la carpeta de datos del editor (nunca en el repo ni en `traducciones/`); exportar/importar TSV (`hoja,row,sub,col,estado`).
- **Suavizar saltos** (espaciado corregido, `reflujar_lineas` + `suavizar_saltos` del repo, sin reimplementar): en la celda (antes/despues + deshacer) y en bloque (tabla, busqueda, mision) con vista previa y **Deshacer suavizado** (journal `suavizado_deshacer.json`, ultimos 20 lotes; maximo 3000 celdas por vez; solo celdas verdes). Nunca cambia palabras, macros ni el numero de trozos. Al **Generar translations.dat** se aplica el mismo suavizado (suavizar_saltos -> mezcla -> construir_dat).
- **Eliminar saltos / Eliminar y suavizar**: quita uno a uno los saltos de presentacion que `construir_dat` admite quitar (los extra); los que exige el japones se conservan. Si no se puede quitar ninguno, avisa y no toca la celda.
- **Por mision / hoja**: lista de hojas (orden por `trabajo/informes/expansion_historia.tsv` si existe, si no por nombre) con celdas, Por hacer, Hecho, rojas/naranjas; busqueda por nombre/ID; conversacion en orden (fila, sub, col); navegacion celda/mision (Alt+flechas), «Guardar y siguiente», «Marcar mision Hecho».

## Desarrollo
```
pip install -r tools/editor/requirements-dev.txt
python -m pytest tools/editor/tests          # usa el checkout (tools/py, textos/); lo que necesita el juego se salta si no esta
python tools/editor/run_editor.py --navegador
```
Variables: `GRIDANIA_EDITOR_HOME` (carpeta de trabajo), `GRIDANIA_EDITOR_REPO` (usar un checkout en vez de la copia descargada).
Tras «Actualizar desde GitHub» el codigo de `tools/py` se recarga sin reiniciar.

## Rendimiento, indice y registro

- Indice persistente (`editor.db`): firma por hoja (size+mtime de ja/fr/traducciones/ediciones). Solo se reindexan las hojas que cambian; "Actualizar indice" (Ctrl = reconstruir todo). Nunca se indexa solo: si falta el indice, la ventana ofrece construirlo (con barra de progreso real y boton Cancelar, que conserva el indice anterior); si esta desactualizado, aparece un aviso.
- Indexado en una transaccion, un solo parseo por hoja y reparto por hojas en procesos (`GRIDANIA_EDITOR_PROCESOS=1` lo desactiva). Columnas `clase` y `flujo` materializadas con indices SQL; las `editor.db` antiguas se migran solas al abrir (ediciones y flujo intactos).
- Registro rotativo `editor.log` en la carpeta de datos (Ayuda > Abrir carpeta de datos y registros): arranque, version, tiempo de cada fase, excepciones no capturadas, peticiones lentas y fallbacks. Si la ventana Edge no carga o no hay Edge/Chrome, se abre el navegador con un aviso visible; si el servidor HTTP muere el proceso termina con mensaje.
- Empaquetado: `--onedir --windowed` (arranque instantaneo, sin pywebview ni pythonnet).
