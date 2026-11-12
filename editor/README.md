# Editor de traducciones Gridania (Windows)

Programa de escritorio (un solo `.exe`) para editar cualquier texto del juego en tu PC. Python 3 + los scripts de `tools/py` del repo
(se descargan al importar; el `.exe` NO lleva textos del juego ni del repo) + interfaz local en ventana propia (pywebview/WebView2; si no
esta, abre el navegador por defecto).

## Obtener el .exe
GitHub > Actions > workflow **editor** > ultima ejecucion > artefacto `GridaniaEditor-win64` (se genera en `windows-latest` con PyInstaller).
Requiere el runtime WebView2 de Windows 10/11 (ya instalado normalmente). Sin el, usa `GridaniaEditor.exe --navegador`.

## Uso
1. **Ajustes**: repo (`escojoncio/gridania`), rama, token personal de GitHub con lectura de *Contents* (se guarda solo en
   `%LOCALAPPDATA%\GridaniaEditor\config.json`; nunca en el repo ni en logs), carpeta `sqpack/ffxiv` del juego y carpeta de destino del `.dat`.
2. **Actualizar desde GitHub**: baja `traducciones/`, `data/`, `textos/ja`, `textos/fr`, `tools/py` y unas tablas de `trabajo/informes`
   (API de GitHub, sin git; la primera vez usa el zip del commit, luego solo lo que cambia por sha). Reindexa.
3. **Extraer del juego** (tras una actualizacion del juego): extrae ja y fr con `tools/py/extract_ja.py` y clasifica cada celda comparando el
   hash `h` de la traduccion con el del japones nuevo:
   **ROJO** nueva o con japones cambiado y sin traduccion vigente; **NARANJA** japones cambiado con traduccion antigua conservada (revisar);
   **VERDE** traducida con hash vigente; **BLANCO** ya existia pero sin traducir. Sin extraccion se compara contra el japones del repo.
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
   (las celdas que no pasan se listan como rechazadas). El indice de busqueda se carga en memoria al importar/indexar.
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
