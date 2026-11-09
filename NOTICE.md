# Notice

## Unofficial Project

FFXIVSpanish Patcher is an unofficial fan-made localization tool.

This project is not affiliated with, endorsed by, sponsored by, approved by, or supported by Square Enix.

Final Fantasy XIV, FFXIV, Square Enix, and all related names, trademarks, logos, text, assets, characters, locations, and other intellectual property are the property of their respective owners.

## No Game File Redistribution

This project does not include, distribute, sell, or provide Final Fantasy XIV game files.

The application is intended to operate only on files from a user's own local Final Fantasy XIV installation.

The project does not provide access to Final Fantasy XIV, does not bypass game ownership, does not bypass subscriptions, does not bypass authentication, and does not bypass any licensing restrictions.

## No Modification of the Original Installation

FFXIVSpanish Patcher is designed to generate separate mod package files for user-side installation through compatible mod tools.

The application is not intended to permanently modify or replace the original Final Fantasy XIV installation files.

Users are responsible for understanding and complying with the terms, rules, and policies that apply to their own use of Final Fantasy XIV and any third-party modding tools.

## Localization Data

Original Spanish translations, glossaries, terminology choices, localization notes, and other linguistic assets authored for this project belong to their respective authors unless explicitly stated otherwise.

Unless a specific file or directory states otherwise, the MIT License in this repository applies only to the application source code and not to localization data, translation files, glossaries, extracted game text, generated mod packages, or other non-code assets.

## Third-Party Tools and Dependencies

This project may interoperate with third-party tools or libraries. Those tools and libraries remain subject to their own licenses, terms, and notices.

Mention of third-party projects does not imply endorsement by their authors or maintainers.

AvaloniaEdit provides the virtualized,
selectable log surface and is distributed under the MIT License. Avalonia, CommunityToolkit.Mvvm,
Lumina, Lumina.Excel, Tmds.DBus.Protocol, xUnit and other development/runtime dependencies remain
subject to their respective licenses and copyright notices as distributed by their authors.
ZstdSharp.Port provides the managed Zstandard codec and is distributed under the MIT License.

The interface embeds JetBrains Mono for labels, figures and the console across Windows, Linux and macOS.
JetBrains Mono is copyright The JetBrains Mono Project Authors and is distributed under the SIL Open Font
License 1.1. A copy of that license is included at `src/FFXIVSpanishPatcher.App/Assets/Fonts/OFL.txt`.

## Third-Party Notices

Dependencies distributed in the binary. Licenses were not verified against the package files in the
editing environment (no NuGet cache available); where a copyright holder could not be confirmed it is
marked "see NuGet package". Verify against the `.nuspec`/license files of the pinned versions before
publishing.

| Component | License | Copyright |
| --- | --- | --- |
| Avalonia, Avalonia.Desktop, Avalonia.Themes.Fluent | MIT | see NuGet package |
| Avalonia.Fonts.Inter (Inter font) | see NuGet package (the Inter font is normally SIL OFL 1.1) | see NuGet package |
| AvaloniaEdit (Avalonia.AvaloniaEdit) | MIT | see NuGet package |
| CommunityToolkit.Mvvm | MIT | see NuGet package |
| Lumina, Lumina.Excel | MIT | see NuGet package |
| ZstdSharp.Port | MIT | see NuGet package |
| Tmds.DBus.Protocol | MIT | see NuGet package |
| JetBrains Mono (font) | SIL OFL 1.1 (`src/FFXIVSpanishPatcher.App/Assets/Fonts/OFL.txt`) | The JetBrains Mono Project Authors |

## Derived Work

This project is a derivative of the FFXIV-Spanish-Patcher project (MIT License). The original copyright
and permission notice is preserved in `LICENSE.md`.

The original translation corpus file is not included in this repository. This project ships no `translations.dat`:
the user supplies their own next to the executable. Part of the corpus has been imported as derived data (see below).

The game texts belong to Square Enix and are not distributed by this project.

## Procedencia de traducciones importadas

`traducciones/*.jsonl` contiene entradas con `"origen":"corpus"`: textos espanoles del corpus de FFXIV-Spanish-Patcher
(sobre paginas `_en`) reasignados por hoja/fila/campo a las filas japonesas (`tools/py/importar_corpus.py`,
hojas de `tools/py/grupos_interfaz.txt`). Coincidencia solo estructural; la equivalencia semantica no esta verificada.
Condiciones declaradas por el proyecto de origen para los DATOS (citas literales de su `LICENSE.md`, `NOTICE.md` y `CONTRIBUTING.md`):
- "Spanish localization data, translation files, glossaries, terminology databases, extracted game text, generated mod packages, and other linguistic or game-related assets are not covered by this license unless explicitly stated otherwise."
- "Original Spanish translations, glossaries, terminology choices, localization notes, and other linguistic assets authored for this project belong to their respective authors unless explicitly stated otherwise."
- "Unless explicitly stated otherwise, localization and translation contributions are not licensed under the MIT License."
No se ha encontrado en ese repositorio ninguna licencia de datos declarada: la MIT cubre solo el codigo. Hay que resolver el permiso de uso
de estos datos antes de hacer publico este repositorio o de distribuir un `translations.dat` que los contenga. Para retirarlos:
borrar las lineas con `"origen":"corpus"`.

## No Warranty

This project is provided without warranty of any kind.

Use of this project is at the user's own risk. The maintainers are not responsible for account actions, data loss, corrupted files, incompatibilities, game updates, broken mods, or any other consequences arising from use of this project.
