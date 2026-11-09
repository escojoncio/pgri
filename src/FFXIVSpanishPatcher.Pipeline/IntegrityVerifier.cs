using XivSpanish.GameData;

namespace FFXIVSpanishPatcher.Pipeline;

/// <summary>
/// Mandatory post-build structural check of a generated Penumbra v4 mod folder.
/// Returns the list of problems found; an empty list means the folder is structurally sound.
/// </summary>
public interface IIntegrityVerifier
{
    IReadOnlyList<string> Verify(string modFolderPath, IReadOnlyDictionary<string, string> declaredFiles);
}

/// <summary>
/// Default verifier: opens the folder, validates the v4 category manifest against the generated
/// redirects, rejects legacy manifests and unsafe paths, and checks every declared file exists
/// (and every declared EXD has the EXDF magic).
/// </summary>
public sealed class IntegrityVerifier : IIntegrityVerifier
{
    public IReadOnlyList<string> Verify(string modFolderPath, IReadOnlyDictionary<string, string> declaredFiles)
    {
        if (!Directory.Exists(modFolderPath))
        {
            return [$"mod folder not found: {modFolderPath}"];
        }

        var root = Path.GetFullPath(modFolderPath);
        var problems = new List<string>(new ModTreeVerifier().Verify(root, declaredFiles));

        if (File.Exists(Path.Combine(root, "default_mod.json")))
        {
            problems.Add("legacy default_mod.json must not be in a v4 package");
        }

        foreach (var modRelative in declaredFiles.Values)
        {
            var path = Path.Combine(root, modRelative.Replace('/', Path.DirectorySeparatorChar));
            if (!File.Exists(path))
            {
                var message = $"declared file not in package: {modRelative}";
                if (!problems.Contains(message))
                {
                    problems.Add(message);
                }
            }
        }

        return problems;
    }
}
