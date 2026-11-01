using XivSpanish.GameData;
using Xunit;

namespace FFXIVSpanishPatcher.Tests;

public sealed class SeStringRunLengthTests
{
    [Theory]
    [InlineData(255, 0x10)]
    [InlineData(256, 0x10)]
    [InlineData(512, 0x10)]
    [InlineData(256, 0xB9)]
    [InlineData(300, 0xCF)]
    public void Run_LengthWithZeroByte_NeverEmitsNulAndRoundTrips(int length, int marker)
    {
        var nodes = new List<SeNode>
        {
            new SeNode.Run([new SeNode.Literal(new string('a', length))], MarkerByte: (byte)marker),
        };
        var bytes = SeStringTree.Serialize(nodes);

        // el ultimo byte es el terminador; antes de el no puede haber NUL
        var body = bytes.Take(bytes.Length - 1).ToArray();
        Assert.DoesNotContain((byte)0, body);

        Assert.Equal(bytes, SeStringTree.Serialize(SeStringTree.Parse(bytes)));
    }

    [Fact]
    public void Macro_WithLongRunChild_RoundTripsAndKeepsLiteral()
    {
        var text = new string('b', 256);
        var nodes = new List<SeNode>
        {
            new SeNode.Macro(
                Code: 0x08,
                Children:
                [
                    new SeNode.Run([new SeNode.Literal(text)], MarkerByte: 0x10),
                    new SeNode.Literal("xx"),
                ],
                LengthMarker: 0xC1),
        };
        var bytes = SeStringTree.Serialize(nodes);
        Assert.DoesNotContain((byte)0, bytes.Take(bytes.Length - 1).ToArray());

        var raw = bytes[..^1];
        var token = SeStringTreeTokenizer.TokenizeRawText(raw);
        Assert.Contains(text, token, StringComparison.Ordinal);
        Assert.Equal(bytes, SeStringTree.Serialize(SeStringTree.Parse(bytes)));
    }
}
