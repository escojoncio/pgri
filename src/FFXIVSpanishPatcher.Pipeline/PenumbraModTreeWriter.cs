using System.Text.Json;
using System.Text.Json.Serialization;

namespace FFXIVSpanishPatcher.Pipeline;

/// <summary>
/// Writes the categorized Penumbra v4 tree. Every package has the same ten options; selected
/// domains only control the Multi group's initial bitfield, never which EXD pages are written.
/// </summary>
internal sealed class PenumbraModTreeWriter
{
    private readonly SortedDictionary<string, string> _declared = new(StringComparer.Ordinal);
    private readonly IReadOnlyDictionary<string, SortedDictionary<string, string>> _filesByDomain;
    private readonly string _stagingPath;

    public PenumbraModTreeWriter(string stagingPath)
    {
        if (Directory.Exists(stagingPath))
        {
            Directory.Delete(stagingPath, recursive: true);
        }

        Directory.CreateDirectory(stagingPath);
        _stagingPath = Path.GetFullPath(stagingPath);
        _filesByDomain = TranslationCategoryCatalog.All.ToDictionary(
            category => category.Domain,
            _ => new SortedDictionary<string, string>(StringComparer.Ordinal),
            StringComparer.OrdinalIgnoreCase);
    }

    public string StagingPath => _stagingPath;

    private int _exdFileCount;

    /// <summary>Number of patched EXD pages (the static UI textures are not counted).</summary>
    public int FileCount => _exdFileCount;

    public IReadOnlyDictionary<string, string> DeclaredFiles => _declared;

    /// <summary>Writes a patched EXD under its category and records the option-local redirect.</summary>
    public void AddPatchedExd(string exdGamePath, byte[] bytes, string domain)
    {
        if (!TranslationCategoryCatalog.TryGet(domain, out var category))
        {
            throw new InvalidDataException($"unknown translation category: {domain}");
        }

        ValidateGamePath(exdGamePath);
        var modRelative = $"files/categories/{category.Order:D2}-{category.Domain}/{exdGamePath}";
        var destination = ResolveInsideTree(modRelative);
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        File.WriteAllBytes(destination, bytes);

        if (!_declared.TryAdd(exdGamePath, modRelative))
        {
            throw new InvalidDataException($"game path declared by more than one category: {exdGamePath}");
        }

        _filesByDomain[category.Domain].Add(exdGamePath, modRelative);
        _exdFileCount++;
    }

    /// <summary>Writes only v4 metadata; callers verify this tree and publish it as the mod folder.</summary>
    public void WriteTree(PackageMeta meta, IReadOnlyCollection<string>? selectedDomains)
    {
        AddBlankUiTextures();
        var options = TranslationCategoryCatalog.All
            .Select(category => new PenumbraModOption(
                category.DisplayName,
                category.Description,
                _filesByDomain[category.Domain],
                string.Equals(category.Domain, "interfaz", StringComparison.OrdinalIgnoreCase) ? UiLanguageSwaps.Load() : null))
            .ToArray();
        var root = PackageModMetaV4.From(meta, options, TranslationCategoryCatalog.BuildDefaultSettings(selectedDomains));
        WriteJsonAtomically(Path.Combine(_stagingPath, "meta.json"), root);
        TranslationModIdentity.Write(_stagingPath);
    }

    private bool _blankUiTexturesAdded;

    /// <summary>Hides the Japanese title subtitles (language-less ui/icon textures) behind a transparent texture.</summary>
    private void AddBlankUiTextures()
    {
        if (_blankUiTexturesAdded)
        {
            return;
        }

        _blankUiTexturesAdded = true;
        var paths = UiLanguageSwaps.LoadHiddenTextures();
        if (paths.Count == 0 || !TranslationCategoryCatalog.TryGet("interfaz", out var category))
        {
            return;
        }

        var bytes = UiLanguageSwaps.BlankTexture();
        foreach (var gamePath in paths)
        {
            ValidateGamePath(gamePath);
            var modRelative = $"files/categories/{category.Order:D2}-{category.Domain}/{gamePath}";
            var destination = ResolveInsideTree(modRelative);
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            File.WriteAllBytes(destination, bytes);
            if (!_declared.TryAdd(gamePath, modRelative))
            {
                throw new InvalidDataException($"game path declared by more than one category: {gamePath}");
            }

            _filesByDomain[category.Domain].Add(gamePath, modRelative);
        }
    }

    private string ResolveInsideTree(string relativePath)
    {
        var candidate = Path.GetFullPath(Path.Combine(_stagingPath, relativePath.Replace('/', Path.DirectorySeparatorChar)));
        var root = _stagingPath.EndsWith(Path.DirectorySeparatorChar)
            ? _stagingPath
            : _stagingPath + Path.DirectorySeparatorChar;
        if (!candidate.StartsWith(root, StringComparison.Ordinal))
        {
            throw new InvalidDataException($"payload path escapes staging tree: {relativePath}");
        }

        return candidate;
    }

    private static void ValidateGamePath(string gamePath)
    {
        if (string.IsNullOrWhiteSpace(gamePath)
            || gamePath.StartsWith("/", StringComparison.Ordinal)
            || gamePath.Contains(':', StringComparison.Ordinal)
            || gamePath.Contains('\\', StringComparison.Ordinal)
            || gamePath.Split('/').Any(segment => segment is "." or ".." or ""))
        {
            throw new InvalidDataException($"unsafe game path: {gamePath}");
        }
    }

    private static void WriteJsonAtomically(string path, PackageModMetaV4 value)
    {
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(value, PipelineJsonContext.Default.PackageModMetaV4));
            File.Move(temporary, path, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }
    }
}

internal sealed class PackageModMetaV4
{
    [JsonPropertyName("FileVersion")] public int FileVersion => 4;
    [JsonPropertyName("Name")] public string Name { get; init; } = string.Empty;
    [JsonPropertyName("Author")] public string Author { get; init; } = string.Empty;
    [JsonPropertyName("Description")] public string Description { get; init; } = string.Empty;
    [JsonPropertyName("Image")] public string Image => string.Empty;
    [JsonPropertyName("Version")] public string Version { get; init; } = "0.0.0";
    [JsonPropertyName("Website")] public string Website { get; init; } = string.Empty;
    [JsonPropertyName("ModTags")] public string[] ModTags => ["translation", "spanish", "castellano", "español", "text", "UI"];
    [JsonPropertyName("DefaultData")] public PenumbraModContainer DefaultData => new();
    [JsonPropertyName("Groups")] public IReadOnlyList<PenumbraModGroup> Groups { get; init; } = [];

    public static PackageModMetaV4 From(PackageMeta meta, IReadOnlyList<PenumbraModOption> options, int defaultSettings)
        => new()
        {
            Name = meta.Name,
            Author = meta.Author,
            Description = meta.Description,
            Version = meta.Version,
            Website = meta.Website,
            Groups =
            [
                new PenumbraModGroup(
                    TranslationCategoryCatalog.GroupName,
                    "Activa las categorías de traducción que quieras aplicar.",
                    defaultSettings,
                    options),
            ],
        };
}

internal class PenumbraModContainer
{
    public PenumbraModContainer(SortedDictionary<string, string>? files = null, SortedDictionary<string, string>? fileSwaps = null)
    {
        Files = files is { Count: > 0 } ? files : null;
        FileSwaps = fileSwaps is { Count: > 0 } ? fileSwaps : null;
    }

    /// <summary>Game path -> game path swaps (Penumbra v4 option); used to show the English HUD textures to a Japanese client.</summary>
    [JsonPropertyName("FileSwaps")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public SortedDictionary<string, string>? FileSwaps { get; }

    [JsonPropertyName("Files")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public SortedDictionary<string, string>? Files { get; }
}

internal sealed class PenumbraModOption(string name, string description, SortedDictionary<string, string> files, SortedDictionary<string, string>? fileSwaps = null)
    : PenumbraModContainer(files, fileSwaps)
{
    [JsonPropertyName("Name")] public string Name { get; } = name;
    [JsonPropertyName("Description")] public string Description { get; } = description;
}

internal sealed class PenumbraModGroup(string name, string description, int defaultSettings, IReadOnlyList<PenumbraModOption> options)
{
    [JsonPropertyName("Name")] public string Name { get; } = name;
    [JsonPropertyName("Description")] public string Description { get; } = description;
    [JsonPropertyName("Type")] public string Type => "Multi";
    [JsonPropertyName("DefaultSettings")] public int DefaultSettings { get; } = defaultSettings;
    [JsonPropertyName("Options")] public IReadOnlyList<PenumbraModOption> Options { get; } = options;
}
