using System.Diagnostics;
using System.Text.Json;

namespace FFXIVSpanishPatcher.App.Services;

/// <summary>
/// Resolves <c>translations.dat</c>. In a single-file self-extracting publish
/// <see cref="AppContext.BaseDirectory"/> points at the temp extraction folder, so the executable folder is
/// taken from <see cref="Environment.ProcessPath"/> (fallbacks: command line, main module). All inputs are
/// injectable so the resolution can be tested with simulated paths.
/// </summary>
public sealed class TranslationsLocator
{
    public const string FileName = "translations.dat";

    private readonly Func<string?> _processPath;
    private readonly Func<string?> _commandLineArg0;
    private readonly Func<string?> _mainModulePath;
    private readonly Func<string?> _currentDirectory;
    private readonly Func<string?> _savedPath;
    private readonly Action<string> _savePath;
    private readonly Func<string, bool> _fileExists;

    public TranslationsLocator(
        Func<string?> processPath,
        Func<string?> commandLineArg0,
        Func<string?> mainModulePath,
        Func<string?> currentDirectory,
        Func<string?> savedPath,
        Action<string> savePath,
        Func<string, bool> fileExists)
    {
        _processPath = processPath;
        _commandLineArg0 = commandLineArg0;
        _mainModulePath = mainModulePath;
        _currentDirectory = currentDirectory;
        _savedPath = savedPath;
        _savePath = savePath;
        _fileExists = fileExists;
    }

    /// <summary>Locator wired to the real process, working directory and local settings file.</summary>
    public static TranslationsLocator CreateDefault(string? settingsFile = null)
    {
        var settings = settingsFile ?? DefaultSettingsFile();
        return new TranslationsLocator(
            () => Environment.ProcessPath,
            () => Environment.GetCommandLineArgs().FirstOrDefault(),
            () =>
            {
                using var process = Process.GetCurrentProcess();
                return process.MainModule?.FileName;
            },
            () => Directory.GetCurrentDirectory(),
            () => ReadSetting(settings),
            path => WriteSetting(settings, path),
            File.Exists);
    }

    public static string DefaultSettingsFile()
        => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "FFXIVSpanish Patcher",
            "settings.json");

    /// <summary>Folder that contains the executable (not the temp extraction folder), or null.</summary>
    public string? ExecutableDirectory()
    {
        foreach (var source in new[] { _processPath, _commandLineArg0, _mainModulePath })
        {
            string? candidate;
            try
            {
                candidate = source();
            }
            catch
            {
                continue;
            }

            if (string.IsNullOrWhiteSpace(candidate))
            {
                continue;
            }

            // The running dotnet host (dotnet run / tests) is not the app folder.
            var name = Path.GetFileNameWithoutExtension(candidate);
            if (string.Equals(name, "dotnet", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            string? directory;
            try
            {
                directory = Path.GetDirectoryName(Path.GetFullPath(candidate));
            }
            catch
            {
                continue;
            }

            if (!string.IsNullOrEmpty(directory))
            {
                return directory;
            }
        }

        return null;
    }

    /// <summary>Candidate paths in priority order: exe folder, working directory, saved path.</summary>
    public IReadOnlyList<string> Candidates()
    {
        var list = new List<string>();
        void Add(string? path)
        {
            if (!string.IsNullOrWhiteSpace(path) && !list.Contains(path, StringComparer.OrdinalIgnoreCase))
            {
                list.Add(path);
            }
        }

        var exeDir = ExecutableDirectory();
        if (exeDir is not null)
        {
            Add(Path.Combine(exeDir, FileName));
        }

        string? cwd = null;
        try { cwd = _currentDirectory(); } catch { }
        if (!string.IsNullOrWhiteSpace(cwd))
        {
            Add(Path.Combine(cwd, FileName));
        }

        string? saved = null;
        try { saved = _savedPath(); } catch { }
        Add(saved);
        return list;
    }

    /// <summary>First existing candidate, or null.</summary>
    public string? Resolve()
        => Candidates().FirstOrDefault(path => _fileExists(path));

    /// <summary>Remembers a user-chosen file for later runs.</summary>
    public void Remember(string path)
    {
        try { _savePath(path); } catch { /* best effort */ }
    }

    public string NotFoundMessage()
        => $"Falta el fichero de traducciones '{FileName}'. Rutas probadas:{Environment.NewLine}"
           + string.Join(Environment.NewLine, Candidates().Select(path => "  - " + path))
           + $"{Environment.NewLine}Colócalo junto al ejecutable o usa «Seleccionar {FileName}…».";

    private static string? ReadSetting(string settingsFile)
    {
        if (!File.Exists(settingsFile))
        {
            return null;
        }

        using var doc = JsonDocument.Parse(File.ReadAllText(settingsFile));
        return doc.RootElement.TryGetProperty("translationsPath", out var value)
               && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
    }

    private static void WriteSetting(string settingsFile, string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(settingsFile)!);
        File.WriteAllText(settingsFile, JsonSerializer.Serialize(new Dictionary<string, string>
        {
            ["translationsPath"] = path,
        }));
    }
}
