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

    private const string HiddenResourceName = "carteles_ui_ja_ocultar.txt";

    /// <summary>Language-less ui/icon textures that carry the Japanese subtitle of area/instance title cards.</summary>
    public static IReadOnlyList<string> LoadHiddenTextures()
    {
        var paths = new List<string>();
        using var stream = typeof(UiLanguageSwaps).Assembly.GetManifestResourceStream(HiddenResourceName);
        if (stream is null)
        {
            return paths;
        }

        using var reader = new StreamReader(stream);
        string? line;
        while ((line = reader.ReadLine()) is not null)
        {
            line = line.Trim();
            if (line.Length > 0 && line[0] != '#' && line.StartsWith("ui/", StringComparison.Ordinal))
            {
                paths.Add(line);
            }
        }

        return paths;
    }

    /// <summary>Fully transparent 4x4 B8G8R8A8 .tex (80-byte header, one mip, zeroed pixels).</summary>
    public static byte[] BlankTexture()
    {
        const int width = 4;
        const int height = 4;
        var bytes = new byte[80 + (width * height * 4)];
        BitConverter.TryWriteBytes(bytes.AsSpan(0, 4), 0x00800000u);   // attribute: 2D texture
        BitConverter.TryWriteBytes(bytes.AsSpan(4, 4), 0x1450u);       // format: B8G8R8A8
        BitConverter.TryWriteBytes(bytes.AsSpan(8, 2), (ushort)width);
        BitConverter.TryWriteBytes(bytes.AsSpan(10, 2), (ushort)height);
        BitConverter.TryWriteBytes(bytes.AsSpan(12, 2), (ushort)1);    // depth
        bytes[14] = 1;                                                 // mip levels
        bytes[15] = 0;                                                 // array size
        BitConverter.TryWriteBytes(bytes.AsSpan(16, 4), 0u);           // lod offsets
        BitConverter.TryWriteBytes(bytes.AsSpan(20, 4), 1u);
        BitConverter.TryWriteBytes(bytes.AsSpan(24, 4), 2u);
        BitConverter.TryWriteBytes(bytes.AsSpan(28, 4), 80u);          // offset to surface 0
        return bytes;
    }
}
