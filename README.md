# FFXIV Spanish Patcher

Parcheador de Final Fantasy XIV que genera una carpeta de mod «FFXIV Spanish» para Penumbra (cópiala a la carpeta de mods de Penumbra) a partir de un
`translations.dat` propio del usuario.

- Este repositorio contiene solo el código del parcheador. No incluye traducciones ni textos
  del juego, ni ningún dato de Square Enix.
- No está afiliado a Square Enix. No modifica los archivos originales del juego.

## Compilar

Requiere el SDK de .NET indicado en `global.json`.

```bash
dotnet restore --locked-mode
dotnet build -c Release --no-restore
dotnet test -c Release --no-build
```

## Uso

Coloca tu `translations.dat` junto al ejecutable. Sin él, la aplicación muestra un error en la consola.

Licencia: ver `LICENSE.md` y `NOTICE.md`. Fuente JetBrains Mono bajo OFL (`src/FFXIVSpanishPatcher.App/Assets/Fonts/OFL.txt`).
