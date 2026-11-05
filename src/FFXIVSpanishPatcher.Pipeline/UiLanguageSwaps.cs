using System.Reflection;

namespace FFXIVSpanishPatcher.Pipeline;

/// <summary>
/// Localized HUD textures (quest/area/dungeon banners, tutorial icons, ...) live in per-language folders
/// (<c>ui/icon/&lt;group&gt;/ja|en/...</c>). The embedded list maps every <c>ja</c> texture to its <c>en</c>
/// twin so Penumbra can show the English signs to a Japanese client. Paths only: no game bytes.
/// </summary>
internal static class UiLanguageSwaps
{
    private const string ResourceName = "carteles_ui_ja_a_en.tsv";

    public static SortedDictionary<string, string> Load()
    {
        var swaps = new SortedDictionary<string, string>(StringComparer.Ordinal);
        using var stream = typeof(UiLanguageSwaps).Assembly.GetManifestResourceStream(ResourceName);
        if (stream is null)
        {
            return swaps;
        }

        using var reader = new StreamReader(stream);
        string? line;
        while ((line = reader.ReadLine()) is not null)
        {
            if (line.Length == 0 || line[0] == '#')
            {
                continue;
            }

            var parts = line.Split('\t');
            if (parts.Length == 2 && parts[0].StartsWith("ui/", StringComparison.Ordinal) && parts[1].StartsWith("ui/", StringComparison.Ordinal))
            {
                swaps[parts[0]] = parts[1];
            }
        }

        return swaps;
    }
}
