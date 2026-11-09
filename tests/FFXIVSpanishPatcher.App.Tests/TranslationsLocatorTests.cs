using FFXIVSpanishPatcher.App.Services;
using Xunit;

namespace FFXIVSpanishPatcher.App.Tests;

public class TranslationsLocatorTests
{
    private static TranslationsLocator Make(
        string? processPath,
        string? arg0 = null,
        string? module = null,
        string? cwd = null,
        string? saved = null,
        params string[] existing)
    {
        var files = new HashSet<string>(existing, StringComparer.OrdinalIgnoreCase);
        return new TranslationsLocator(
            () => processPath, () => arg0, () => module, () => cwd, () => saved, _ => { }, files.Contains);
    }

    [Fact]
    public void ExecutableFolderWinsOverWorkingDirectory()
    {
        var exeDat = Path.GetFullPath(Path.Combine("/games", "patcher", "translations.dat"));
        var cwdDat = Path.GetFullPath(Path.Combine("/work", "translations.dat"));
        var locator = Make(Path.GetFullPath("/games/patcher/app.exe"), cwd: Path.GetFullPath("/work"),
            existing: [exeDat, cwdDat]);
        Assert.Equal(exeDat, locator.Resolve());
    }

    [Fact]
    public void FallsBackToWorkingDirectoryThenSavedPath()
    {
        var cwdDat = Path.GetFullPath("/work/translations.dat");
        Assert.Equal(cwdDat, Make(Path.GetFullPath("/p/app.exe"), cwd: Path.GetFullPath("/work"),
            existing: [cwdDat]).Resolve());

        var saved = Path.GetFullPath("/user/mi.dat");
        Assert.Equal(saved, Make(Path.GetFullPath("/p/app.exe"), cwd: Path.GetFullPath("/work"),
            saved: saved, existing: [saved]).Resolve());
    }

    [Fact]
    public void ProcessPathFallsBackToArgsThenMainModule()
    {
        var dir = Path.GetFullPath("/x");
        Assert.Equal(dir, Make(null, arg0: Path.GetFullPath("/x/app.exe")).ExecutableDirectory());
        Assert.Equal(dir, Make("", arg0: null, module: Path.GetFullPath("/x/app.exe")).ExecutableDirectory());
        Assert.Null(Make(null).ExecutableDirectory());
    }

    [Fact]
    public void DotnetHostIsIgnored()
    {
        var dir = Path.GetFullPath("/y");
        Assert.Equal(dir, Make(Path.GetFullPath("/usr/bin/dotnet"), arg0: Path.GetFullPath("/y/app.dll"))
            .ExecutableDirectory());
    }

    [Fact]
    public void NotFoundMessageListsAllTriedPaths()
    {
        var locator = Make(Path.GetFullPath("/p/app.exe"), cwd: Path.GetFullPath("/work"),
            saved: Path.GetFullPath("/user/mi.dat"));
        Assert.Null(locator.Resolve());
        var message = locator.NotFoundMessage();
        Assert.Equal(3, locator.Candidates().Count);
        foreach (var candidate in locator.Candidates())
        {
            Assert.Contains(candidate, message);
        }
    }

    [Fact]
    public void ThrowingSourcesAreTolerated()
    {
        var locator = new TranslationsLocator(
            () => throw new InvalidOperationException(), () => Path.GetFullPath("/z/app.exe"), () => null,
            () => throw new InvalidOperationException(), () => throw new InvalidOperationException(),
            _ => { }, _ => false);
        Assert.Single(locator.Candidates());
    }
}
