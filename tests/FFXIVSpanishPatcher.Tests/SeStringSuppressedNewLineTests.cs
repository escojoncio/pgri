using System.Text;
using XivSpanish.GameData;
using XivSpanish.Packager;
using XivSpanish.Translation;
using Xunit;

namespace FFXIVSpanishPatcher.Tests;

/// <summary>
/// A <c>&lt;NewLine&gt;</c> immediately followed by U+E0F0 is turned into a space (the client then
/// wraps by itself). The NewLine token stays in the target, so the structural validation against
/// the source is unchanged; the marker is never written to the game; hard newlines (inside a run or
/// macro bracket, at the start or end, glued to another token) cannot be suppressed; without the
/// marker everything behaves exactly as before.
/// </summary>
public sealed class SeStringSuppressedNewLineTests
{
    private const string M = "";
    private static readonly byte[] NewLineBytes = [0x02, 0x10, 0x01, 0x03];
    private static readonly byte[] MarkerUtf8 = [0xEE, 0x83, 0xB0];

    private static byte[] Text(string value) => Encoding.UTF8.GetBytes(value);

    private static byte[] Join(params byte[][] parts) => parts.SelectMany(p => p).ToArray();

    private static bool ContainsMarkerBytes(byte[] bytes)
    {
        for (var i = 0; i + MarkerUtf8.Length <= bytes.Length; i++)
        {
            if (bytes.AsSpan(i, MarkerUtf8.Length).SequenceEqual(MarkerUtf8))
            {
                return true;
            }
        }

        return false;
    }

    [Fact]
    public void MarkerUtf8Constant_MatchesTheMarkerCharacter()
    {
        Assert.Equal(MarkerUtf8, Text(M));
        Assert.Equal('', SeStringSuppressedNewLine.Marker);
    }

    [Fact]
    public void SuppressedSourceNewLine_BecomesASingleSpace()
    {
        var vanilla = Join(Text("Hola"), NewLineBytes, Text("Mundo"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        Assert.Equal("Hola<NewLine>Mundo", source);

        var target = "Hola<NewLine>" + M + "Mundo";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);

        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(Text("Hola Mundo"), result);
        Assert.False(ContainsMarkerBytes(result));
    }

    [Fact]
    public void WithoutTheMarker_BehaviourIsUnchanged()
    {
        var vanilla = Join(Text("Hola"), NewLineBytes, Text("Mundo"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);

        var target = "Hola<NewLine>Mundo";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(vanilla, result);
    }

    [Fact]
    public void SpaceIsNotDuplicated_WhenEitherSideAlreadyHasOne()
    {
        var vanilla = Join(Text("Hola"), NewLineBytes, Text("Mundo"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);

        Assert.True(SeStringTree.TryTranslate(vanilla, source, "Hola <NewLine>" + M + "Mundo", out var trailing, out var reason1), reason1);
        Assert.Equal(Text("Hola Mundo"), trailing);

        Assert.True(SeStringTree.TryTranslate(vanilla, source, "Hola<NewLine>" + M + " Mundo", out var leading, out var reason2), reason2);
        Assert.Equal(Text("Hola Mundo"), leading);
    }

    [Fact]
    public void OnlyTheMarkedNewLine_IsSuppressed_TheOthersKeepTheirBytes()
    {
        var vanilla = Join(Text("A"), NewLineBytes, Text("B"), NewLineBytes, Text("C"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        Assert.Equal("A<NewLine>B<NewLine#2>C", source);

        var target = "A<NewLine>" + M + "B<NewLine#2>C";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(Join(Text("A B"), NewLineBytes, Text("C")), result);

        var second = "A<NewLine>B<NewLine#2>" + M + "C";
        Assert.True(SeStringCompatibilityValidator.Validate(source, second).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, second, out var result2, out var reason2), reason2);
        Assert.Equal(Join(Text("A"), NewLineBytes, Text("B C")), result2);
    }

    [Fact]
    public void EmptyMarkedChunk_MeansNothing_AndNeverCreatesABlankLine()
    {
        var vanilla = Join(Text("A"), NewLineBytes, Text("B"), NewLineBytes, Text("C"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);

        // A <NL suppressed> [empty] <NL kept> C  ->  "A" NL "C": the pending space dies at the kept NewLine.
        var keepSecond = "A<NewLine>" + M + "<NewLine#2>C";
        Assert.True(SeStringCompatibilityValidator.Validate(source, keepSecond).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, keepSecond, out var kept, out var reason1), reason1);
        Assert.Equal(Join(Text("A"), NewLineBytes, Text("C")), kept);

        // Both suppressed, the middle chunk empty: a single space between A and C.
        var both = "A<NewLine>" + M + "<NewLine#2>" + M + "C";
        Assert.True(SeStringCompatibilityValidator.Validate(source, both).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, both, out var flowed, out var reason2), reason2);
        Assert.Equal(Text("A C"), flowed);
    }

    [Fact]
    public void SuppressedExtraNewLine_IsAcceptedAndDroppedToo()
    {
        var vanilla = Join(Text("A"), NewLineBytes, Text("B"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);

        var target = "A<NewLine>B<NewLine#2>" + M + "C";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(Join(Text("A"), NewLineBytes, Text("B C")), result);
    }

    [Fact]
    public void PlainSourceWithoutNewLine_AcceptsASuppressedSynthesizedNewLine()
    {
        var vanilla = Text("Hola mundo");
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);

        var target = "Hola<NewLine>" + M + "mundo";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(Text("Hola mundo"), result);
    }

    [Fact]
    public void SpaceIsWrittenBeforeAFollowingTokenToo()
    {
        // 0x41 is an arbitrary leaf macro; its token name comes from the tokenizer.
        byte[] other = [0x02, 0x41, 0x01, 0x03];
        var vanilla = Join(Text("A"), NewLineBytes, other, Text("B"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        var otherToken = System.Text.RegularExpressions.Regex.Match(source, "<(?!NewLine)[^>]+>").Value;
        Assert.NotEqual(string.Empty, otherToken);

        var target = "A<NewLine>" + M + otherToken + "B";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(Join(Text("A "), other, Text("B")), result);
    }

    [Fact]
    public void HardNewLines_CannotBeSuppressed()
    {
        var vanilla = Join(NewLineBytes, Text("A"), NewLineBytes, NewLineBytes, Text("B"), NewLineBytes);
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        Assert.Equal("<NewLine>A<NewLine#2><NewLine#3>B<NewLine#4>", source);

        // At the start of the string.
        var atStart = SeStringCompatibilityValidator.Validate(source, "<NewLine>" + M + "A<NewLine#2><NewLine#3>B<NewLine#4>");
        Assert.False(atStart.IsCompatible);
        Assert.Contains(atStart.Violations, v => v.Kind == SeStringViolationKind.StrayDelimiter);

        // Glued to the previous NewLine (paragraph break).
        var glued = SeStringCompatibilityValidator.Validate(source, "<NewLine>A<NewLine#2><NewLine#3>" + M + "B<NewLine#4>");
        Assert.False(glued.IsCompatible);
        Assert.Contains(glued.Violations, v => v.Kind == SeStringViolationKind.StrayDelimiter);

        // Nothing after the marker (trailing newline).
        var atEnd = SeStringCompatibilityValidator.Validate(source, "<NewLine>A<NewLine#2><NewLine#3>B<NewLine#4>" + M);
        Assert.False(atEnd.IsCompatible);
        Assert.Contains(atEnd.Violations, v => v.Kind == SeStringViolationKind.StrayDelimiter);
    }

    [Fact]
    public void StrayMarker_IsRejectedByValidatorAndNeverReachesTheGame()
    {
        var vanilla = Join(Text("Hola"), NewLineBytes, Text("Mundo"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);

        var stray = "Hola" + M + "<NewLine>Mundo";
        var report = SeStringCompatibilityValidator.Validate(source, stray);
        Assert.False(report.IsCompatible);
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.StrayDelimiter);
        Assert.False(SeStringTree.TryTranslate(vanilla, source, stray, out _, out _));

        // Two markers after one NewLine: the second is not attached.
        var twice = "Hola<NewLine>" + M + M + "Mundo";
        Assert.False(SeStringCompatibilityValidator.Validate(source, twice).IsCompatible);
        Assert.False(SeStringTree.TryTranslate(vanilla, source, twice, out _, out _));
    }

    [Fact]
    public void SuppressedNewLineInsideRun_IsRejected()
    {
        var vanilla = SeStringTree.Serialize(
        [
            new SeNode.Run(
            [
                new SeNode.Literal("x"),
                new SeNode.Macro(Code: 0x10, Children: [], LengthMarker: 0x01),
                new SeNode.Literal("y"),
            ], MarkerByte: 0x10),
        ])[..^1];
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        Assert.Equal("<Run>x<NewLine>y<RunEnd>", source);

        Assert.True(SeStringCompatibilityValidator.Validate(source, "<Run>x<NewLine>y<RunEnd>").IsCompatible);

        var target = "<Run>x<NewLine>" + M + "y<RunEnd>";
        var report = SeStringCompatibilityValidator.Validate(source, target);
        Assert.False(report.IsCompatible);
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.ExtraPayload);
        Assert.False(SeStringTree.TryTranslate(vanilla, source, target, out _, out _));
    }

    [Fact]
    public void SuppressedNewLineBeforeTheLastMacroEnd_IsRejected_AfterItIsAccepted()
    {
        var before = SeStringCompatibilityValidator.Validate(
            "A<NewLine>B<Payload40>x<MacroEnd>C",
            "A<NewLine>" + M + "B<Payload40>x<MacroEnd>C");
        Assert.False(before.IsCompatible);
        Assert.Contains(before.Violations, v => v.Kind == SeStringViolationKind.ExtraPayload);

        var after = SeStringCompatibilityValidator.Validate(
            "A<Payload40>x<MacroEnd>B<NewLine>C",
            "A<Payload40>x<MacroEnd>B<NewLine>" + M + "C");
        Assert.True(after.IsCompatible);
    }

    [Fact]
    public void FlatPaths_RefuseATargetWithTheMarker()
    {
        var vanilla = Join(Text("Hola"), NewLineBytes, Text("Mundo"));
        var segments = SeStringParser.Parse(vanilla);
        var source = SeStringTokenizer.Tokenize(segments).Text;
        var target = "Hola<NewLine>" + M + "Mundo";

        Assert.False(SeStringParser.TryReplaceTokenized(segments, source, target, out _, out _));
        Assert.False(SeStringParser.TryReplace(segments, "Hola", "Ho" + M + "la", out _, out _));
    }

    [Fact]
    public void StandardMacroTargetOnPlainSource_NeverWritesTheMarkerAsText()
    {
        var vanilla = Text("Hola mundo");
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        var target = "Hola" + M + " <Gender>a<GenderElse>o<GenderEnd>";

        Assert.False(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.False(SeStringTree.TryTranslate(vanilla, source, target, out _, out _));
    }

    [Fact]
    public void ManifestGate_ValidatesPlainSourcesThatCarryTheMarker()
    {
        var good = Entry("Hola mundo", "Hola<NewLine>" + M + "mundo");
        Assert.Empty(ManifestSeStringGate.Check([good]));

        var leaked = Entry("Hola mundo", "Hola" + M + "mundo");
        var violation = Assert.Single(ManifestSeStringGate.Check([leaked]));
        Assert.Contains(violation.Report.Violations, v => v.Kind == SeStringViolationKind.StrayDelimiter);
    }

    private static TranslationEntry Entry(string source, string target) => new()
    {
        Source = source,
        Target = target,
        Status = TranslationEntryStatus.Approved,
        SourceKey = new TranslationSourceKey
        {
            Sheet = "quest/045/Test",
            RowId = 1,
            Field = "Column1",
            ExdPath = "exd/quest/045/test_0_en.exd",
        },
    };
}
