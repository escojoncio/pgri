using System.Text;
using XivSpanish.GameData;
using XivSpanish.Packager;
using XivSpanish.Translation;
using Xunit;

namespace FFXIVSpanishPatcher.Tests;

/// <summary>
/// Non-canonical UTF-8 (overlong, surrogate, &gt; U+10FFFF) inside a macro body must be kept as
/// reversible RawByte nodes, never decoded to U+FFFD. Synthetic bytes only.
/// </summary>
public sealed class SeStringOverlongUtf8Tests
{
    // 02 28 0C | FF 05 'EObj' | F6 1E C0 A0 01 | 03  (C0 A0 = overlong encoding of U+0020)
    private static byte[] Macro() =>
    [
        0x02, 0x28, 0x0C,
        0xFF, 0x05, (byte)'E', (byte)'O', (byte)'b', (byte)'j',
        0xF6, 0x1E, 0xC0, 0xA0, 0x01,
        0x03,
    ];

    private static byte[] Row(string before, string after)
    {
        var bytes = new List<byte>();
        bytes.AddRange(Encoding.UTF8.GetBytes(before));
        bytes.AddRange(Macro());
        bytes.AddRange(Encoding.UTF8.GetBytes(after));
        bytes.Add(0x00);
        return bytes.ToArray();
    }

    [Fact]
    public void OverlongBytes_ParseSerialize_ByteIdentical()
    {
        var row = Row("qqq", "end");
        Assert.Equal(row, SeStringTree.Serialize(SeStringTree.Parse(row)));
    }

    [Fact]
    public void OverlongBytes_NeverBecomeReplacementCharacter()
    {
        var text = SeStringTreeTokenizer.TokenizeRawText(Row("qqq", "end"));
        Assert.DoesNotContain('�', text);
    }

    [Theory]
    [InlineData(new byte[] { 0xC1, 0xBF })]            // overlong 2-byte
    [InlineData(new byte[] { 0xE0, 0x80, 0x80 })]      // overlong 3-byte
    [InlineData(new byte[] { 0xED, 0xA0, 0x80 })]      // surrogate
    [InlineData(new byte[] { 0xF0, 0x80, 0x80, 0x80 })] // overlong 4-byte
    [InlineData(new byte[] { 0xF4, 0x90, 0x80, 0x80 })] // > U+10FFFF
    public void NonCanonicalSequences_RoundTripAsRawBytes(byte[] invalid)
    {
        var row = new List<byte>(Encoding.UTF8.GetBytes("ab"));
        row.AddRange(invalid);
        row.AddRange(Encoding.UTF8.GetBytes("cd"));
        row.Add(0x00);
        var arr = row.ToArray();

        Assert.Equal(arr, SeStringTree.Serialize(SeStringTree.Parse(arr)));
        Assert.DoesNotContain('�', SeStringTreeTokenizer.TokenizeRawText(arr));
    }

    [Fact]
    public void CanonicalMultibyteText_StillLiteral()
    {
        var row = Encoding.UTF8.GetBytes("aéあ\U0001F600z").Append((byte)0).ToArray();
        var nodes = SeStringTree.Parse(row);
        var lit = Assert.IsType<SeNode.Literal>(Assert.Single(nodes));
        Assert.Equal("aéあ\U0001F600z", lit.Text);
        Assert.Equal(row, SeStringTree.Serialize(nodes));
    }

    [Fact]
    public void TryTranslate_RewritesTextAroundOverlongMacro_KeepingBytes()
    {
        var row = Row("qqq", "end");
        var vanilla = row[..^1];
        var tok = SeStringTreeTokenizer.Tokenize(SeStringTree.Parse(row));
        var target = tok.Text.Replace("qqq", "rrr", StringComparison.Ordinal);
        Assert.NotEqual(tok.Text, target);

        Assert.True(SeStringTree.TryTranslate(vanilla, tok.Text, target, out var result, out var reason), reason);

        var expected = Row("rrr", "end")[..^1];
        Assert.Equal(expected, result);
    }

    [Fact]
    public void ManifestGate_DoesNotRejectOverlongMacroRow()
    {
        var row = Row("qqq", "end");
        var tok = SeStringTreeTokenizer.Tokenize(SeStringTree.Parse(row));
        var entry = new TranslationEntry
        {
            Source = tok.Text,
            Target = tok.Text.Replace("qqq", "rrr", StringComparison.Ordinal),
            Status = TranslationEntryStatus.Approved,
            SourceKey = new TranslationSourceKey
            {
                Sheet = "quest/055/Test",
                RowId = 1,
                Field = "Column1",
                ExdPath = "exd/quest/055/test_0_en.exd",
            },
        };

        Assert.Empty(ManifestSeStringGate.Check([entry]));
    }
}
