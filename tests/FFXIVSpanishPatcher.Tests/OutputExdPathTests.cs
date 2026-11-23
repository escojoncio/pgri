using FFXIVSpanishPatcher.Pipeline;
using Xunit;

namespace FFXIVSpanishPatcher.Tests;

public sealed class OutputExdPathTests
{
    [Theory]
    [InlineData("exd/addon_0_ja.exd", "exd/addon_0_en.exd")]
    [InlineData("exd/quest/045/chrhdb811_04542_0_ja.exd", "exd/quest/045/chrhdb811_04542_0_en.exd")]
    [InlineData("exd/addon_0_en.exd", "exd/addon_0_en.exd")]
    [InlineData("exd/addon_0.exd", "exd/addon_0.exd")]
    public void Ja_pages_are_declared_under_the_en_path(string input, string expected)
        => Assert.Equal(expected, PatchPipeline.OutputExdPath(input));
}
