using System.Text;
using XivSpanish.GameData;
using Xunit;

namespace FFXIVSpanishPatcher.Tests;

/// <summary>
/// The target may carry MORE <c>&lt;NewLine&gt;</c> (macro 0x10, bytes <c>02 10 01 03</c>) tokens
/// than the source, and ONLY that token: every other token and the order stay exact, an extra
/// newline never sits inside a length-prefixed run, and a source without any NewLine accepts none.
/// </summary>
public sealed class SeStringExtraNewLineTests
{
    private static readonly byte[] NewLineBytes = [0x02, 0x10, 0x01, 0x03];

    private static byte[] Text(string value) => Encoding.UTF8.GetBytes(value);

    private static byte[] Join(params byte[][] parts) => parts.SelectMany(p => p).ToArray();

    [Fact]
    public void ExtraNewLine_IsAcceptedAndSynthesizedWithSourceBytes()
    {
        var vanilla = Join(Text("Hola"), NewLineBytes, Text("Mundo"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        Assert.Equal("Hola<NewLine>Mundo", source);

        var target = "Hola<NewLine>Mundo<NewLine#2>Fin";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);

        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(Join(Text("Hola"), NewLineBytes, Text("Mundo"), NewLineBytes, Text("Fin")), result);
    }

    [Fact]
    public void SeveralExtraNewLines_AreAcceptedWhenNumberedBeyondTheSource()
    {
        var vanilla = Join(Text("A"), NewLineBytes, Text("B"), NewLineBytes, Text("C"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        Assert.Equal("A<NewLine>B<NewLine#2>C", source);

        var target = "A<NewLine><NewLine#3>B<NewLine#2>C<NewLine#4>";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);

        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(
            Join(Text("A"), NewLineBytes, NewLineBytes, Text("B"), NewLineBytes, Text("C"), NewLineBytes),
            result);
    }

    [Fact]
    public void MissingNewLine_IsRejected()
    {
        var vanilla = Join(Text("Hola"), NewLineBytes, Text("Mundo"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        var target = "Hola Mundo";

        var report = SeStringCompatibilityValidator.Validate(source, target);
        Assert.False(report.IsCompatible);
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.MissingPayload);
    }

    [Fact]
    public void ExtraNonNewLineToken_IsRejected()
    {
        var vanilla = Join(Text("Hola"), NewLineBytes, Text("Mundo"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);

        var withOtherToken = "Hola<NewLine>Mundo<Payload40>";
        var report = SeStringCompatibilityValidator.Validate(source, withOtherToken);
        Assert.False(report.IsCompatible);
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.ExtraPayload);

        // An extra NewLine does not excuse an additional foreign token next to it.
        var mixed = "Hola<NewLine>Mundo<NewLine#2><Payload40>";
        Assert.False(SeStringCompatibilityValidator.Validate(source, mixed).IsCompatible);
        Assert.False(SeStringTree.TryTranslate(vanilla, source, mixed, out _, out _));
    }

    [Fact]
    public void DuplicatedExtraNewLine_IsRejected()
    {
        var vanilla = Join(Text("Hola"), NewLineBytes, Text("Mundo"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        var target = "Hola<NewLine>Mundo<NewLine#2><NewLine#2>";

        Assert.False(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.False(SeStringTree.TryTranslate(vanilla, source, target, out _, out _));
    }

    [Fact]
    public void ReorderedTokens_AreRejectedEvenWithAnExtraNewLine()
    {
        // 0x41 is an arbitrary leaf macro; its token name comes from the tokenizer (derived below).
        byte[] other = [0x02, 0x41, 0x01, 0x03];
        var vanilla = Join(Text("A"), NewLineBytes, Text("B"), other, Text("C"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        Assert.Contains("<NewLine>", source, StringComparison.Ordinal);

        var otherToken = System.Text.RegularExpressions.Regex.Match(source, "<(?!NewLine)[^>]+>").Value;
        Assert.NotEqual(string.Empty, otherToken);

        var target = "A" + otherToken + "B<NewLine>C<NewLine#2>";
        var report = SeStringCompatibilityValidator.Validate(source, target);
        Assert.False(report.IsCompatible);
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.ReorderedPayloads);
    }

    [Fact]
    public void ExtraNewLineInsideRun_IsRejected()
    {
        var vanillaWithTerminator = SeStringTree.Serialize(
        [
            new SeNode.Literal("A"),
            new SeNode.Macro(Code: 0x10, Children: [], LengthMarker: 0x01),
            new SeNode.Run([new SeNode.Literal("x")], MarkerByte: 0x10),
        ]);
        var vanilla = vanillaWithTerminator[..^1];
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        Assert.Equal("A<NewLine><Run>x<RunEnd>", source);

        // Outside the run the extra is fine ...
        Assert.True(SeStringCompatibilityValidator.Validate(source, "A<NewLine><NewLine#2><Run>x<RunEnd>").IsCompatible);

        // ... inside the run it would change the recomputed length prefix: rejected.
        var inside = "A<NewLine><Run>x<NewLine#2><RunEnd>";
        var report = SeStringCompatibilityValidator.Validate(source, inside);
        Assert.False(report.IsCompatible);
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.ExtraPayload);
        Assert.False(SeStringTree.TryTranslate(vanilla, source, inside, out _, out _));
    }

    [Fact]
    public void PlainSourceWithoutNewLine_AcceptsOneSynthesizedNewLine()
    {
        var vanilla = Text("Hola mundo");
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        Assert.Equal("Hola mundo", source);

        var target = "Hola<NewLine>mundo";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(Join(Text("Hola"), NewLineBytes, Text("mundo")), result);
    }

    [Fact]
    public void PlainSourceWithoutNewLine_AcceptsTwoSynthesizedNewLines()
    {
        var vanilla = Text("Hola mundo cruel");
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);

        var target = "Hola<NewLine>mundo<NewLine#2>cruel";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(Join(Text("Hola"), NewLineBytes, Text("mundo"), NewLineBytes, Text("cruel")), result);
    }

    [Fact]
    public void PlainSourceWithoutNewLine_RejectsMoreThanThreeNewLines()
    {
        var vanilla = Text("Hola");
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);

        var three = "a<NewLine>b<NewLine#2>c<NewLine#3>d";
        Assert.True(SeStringCompatibilityValidator.Validate(source, three).IsCompatible);

        var four = "a<NewLine>b<NewLine#2>c<NewLine#3>d<NewLine#4>e";
        Assert.False(SeStringCompatibilityValidator.Validate(source, four).IsCompatible);
        Assert.False(SeStringTree.TryTranslate(vanilla, source, four, out _, out _));
    }

    [Fact]
    public void PlainSourceWithoutNewLine_RejectsDuplicatedOrForeignTokens()
    {
        var vanilla = Text("Hola");
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);

        Assert.False(SeStringCompatibilityValidator.Validate(source, "a<NewLine>b<NewLine>c").IsCompatible);
        Assert.False(SeStringTree.TryTranslate(vanilla, source, "a<NewLine>b<NewLine>c", out _, out _));
        Assert.False(SeStringCompatibilityValidator.Validate(source, "a<NewLine>b<Payload40>").IsCompatible);
    }

    [Fact]
    public void SynthesizedNewLineInsideRun_IsRejectedForSourceWithoutNewLine()
    {
        var vanilla = SeStringTree.Serialize(
        [
            new SeNode.Literal("A"),
            new SeNode.Run([new SeNode.Literal("x")], MarkerByte: 0x10),
        ])[..^1];
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        Assert.Equal("A<Run>x<RunEnd>", source);

        Assert.True(SeStringCompatibilityValidator.Validate(source, "A<NewLine><Run>x<RunEnd>").IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, "A<NewLine><Run>x<RunEnd>", out _, out var reason), reason);

        var inside = "A<Run>x<NewLine><RunEnd>";
        var report = SeStringCompatibilityValidator.Validate(source, inside);
        Assert.False(report.IsCompatible);
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.ExtraPayload);
        Assert.False(SeStringTree.TryTranslate(vanilla, source, inside, out _, out _));
    }

    [Fact]
    public void SynthesizedNewLineBeforeLastMacroEnd_IsRejectedForSourceWithoutNewLine()
    {
        var source = "A<Payload40>x<MacroEnd>B";

        Assert.True(SeStringCompatibilityValidator.Validate(source, "A<Payload40>x<MacroEnd>B<NewLine>").IsCompatible);

        var report = SeStringCompatibilityValidator.Validate(source, "A<Payload40>x<NewLine><MacroEnd>B");
        Assert.False(report.IsCompatible);
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.ExtraPayload);
    }
}
