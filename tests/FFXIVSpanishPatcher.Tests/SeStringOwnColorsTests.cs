using System.Text;
using XivSpanish.GameData;
using XivSpanish.Packager;
using XivSpanish.Translation;
using Xunit;

namespace FFXIVSpanishPatcher.Tests;

/// <summary>
/// Target-authored colour spans: <c>&lt;UIColor:f201yy&gt;text&lt;UIColorEnd&gt;</c> in the target is rebuilt as the
/// ColorType (0x48) + EdgeColorType (0x49) macros the game uses, replacing the source's own colour tokens
/// (their count, order and code may differ from the target's). Without own colours nothing changes. Invalid
/// spans (nested, unclosed, out of range, mixed with plain colour tokens, inside runs) are rejected, and the
/// authoring tags never reach the game as visible text.
/// </summary>
public sealed class SeStringOwnColorsTests
{
    private static readonly byte[] NewLineBytes = [0x02, 0x10, 0x01, 0x03];

    private static byte[] Text(string value) => Encoding.UTF8.GetBytes(value);

    private static byte[] Join(params byte[][] parts) => parts.SelectMany(p => p).ToArray();

    // <ColorType> + <EdgeColorType> for UIColor 0x01yy / 0x01yy+1, and the double reset.
    private static byte[] Open(byte code) => [0x02, 0x48, 0x04, 0xF2, 0x01, code, 0x03, 0x02, 0x49, 0x04, 0xF2, 0x01, (byte)(code + 1), 0x03];

    private static readonly byte[] Close = [0x02, 0x49, 0x02, 0x01, 0x03, 0x02, 0x48, 0x02, 0x01, 0x03];

    // "Texto <f4>A<reset> y <f4>B<reset> fin" -- two spans with the Japanese colour f201f4.
    private static byte[] TwoSpanVanilla() => Join(
        Text("Texto "), Open(0xF4), Text("A"), Close, Text(" y "), Open(0xF4), Text("B"), Close, Text(" fin"));

    private const string TwoSpanSource =
        "Texto <ColorType><EdgeColorType>A<EdgeColorType#2><ColorType#2> y <ColorType#3><EdgeColorType#3>B<EdgeColorType#4><ColorType#4> fin";

    [Fact]
    public void SourceTokenization_IsTheExpectedOne()
    {
        Assert.Equal(TwoSpanSource, SeStringTreeTokenizer.TokenizeRawText(TwoSpanVanilla()));
    }

    [Fact]
    public void OwnColor_ReplacesSourceColours_WithADifferentCodeAndPlacement()
    {
        var vanilla = TwoSpanVanilla();
        // One span instead of two, with the French code f201f6.
        var target = "Texto A y <UIColor:f201f6>B<UIColorEnd> fin";

        Assert.True(SeStringCompatibilityValidator.Validate(TwoSpanSource, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, TwoSpanSource, target, out var result, out var reason), reason);
        Assert.Equal(Join(Text("Texto A y "), Open(0xF6), Text("B"), Close, Text(" fin")), result);
    }

    [Fact]
    public void OwnColor_CanOmitAllSourceColours_AndRebuildsExactBytes()
    {
        var vanilla = TwoSpanVanilla();
        var target = "<UIColor:f201f6>Texto<UIColorEnd> A y B fin";

        Assert.True(SeStringCompatibilityValidator.Validate(TwoSpanSource, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, TwoSpanSource, target, out var result, out var reason), reason);
        Assert.Equal(Join(Open(0xF6), Text("Texto"), Close, Text(" A y B fin")), result);
        // The re-tokenization of the written bytes is what the Python emulation expects.
        Assert.Equal(
            "<ColorType><EdgeColorType>Texto<EdgeColorType#2><ColorType#2> A y B fin",
            SeStringTreeTokenizer.TokenizeRawText(result));
    }

    [Fact]
    public void OwnColor_KeepsOtherSourceTokens_AndTheirOrder()
    {
        var vanilla = Join(Text("A"), NewLineBytes, Open(0xF4), Text("B"), Close, NewLineBytes, Text("C"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        Assert.Equal("A<NewLine><ColorType><EdgeColorType>B<EdgeColorType#2><ColorType#2><NewLine#2>C", source);

        var good = "A<NewLine>B <UIColor:f201f8>C<UIColorEnd><NewLine#2>fin";
        Assert.True(SeStringCompatibilityValidator.Validate(source, good).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, good, out var result, out var reason), reason);
        Assert.Equal(Join(Text("A"), NewLineBytes, Text("B "), Open(0xF8), Text("C"), Close, NewLineBytes, Text("fin")), result);

        // A source NewLine still cannot be dropped.
        var lost = "AB <UIColor:f201f8>C<UIColorEnd><NewLine#2>fin";
        Assert.False(SeStringCompatibilityValidator.Validate(source, lost).IsCompatible);
    }

    [Fact]
    public void OwnColor_WorksOnASourceWithoutAnyColour()
    {
        var vanilla = Text("Hola mundo");
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        var target = "Hola <UIColor:f201fa>mundo<UIColorEnd>";

        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(Join(Text("Hola "), Open(0xFA), Text("mundo"), Close), result);
    }

    [Fact]
    public void WithoutOwnColours_BehaviourIsUnchanged()
    {
        var vanilla = TwoSpanVanilla();
        Assert.True(SeStringCompatibilityValidator.Validate(TwoSpanSource, TwoSpanSource).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, TwoSpanSource, TwoSpanSource, out var result, out var reason), reason);
        Assert.Equal(vanilla, result);

        var dropped = "Texto A y <ColorType#3><EdgeColorType#3>B<EdgeColorType#4><ColorType#4> fin";
        var report = SeStringCompatibilityValidator.Validate(TwoSpanSource, dropped);
        Assert.False(report.IsCompatible);
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.MissingPayload);
    }

    [Theory]
    [InlineData("Texto <UIColor:f201f6>A y B fin")]
    [InlineData("Texto A<UIColorEnd> y B fin")]
    [InlineData("Texto <UIColor:f201f6>A <UIColor:f201f8>y<UIColorEnd> B<UIColorEnd> fin")]
    [InlineData("Texto <UIColor:f2023b>A<UIColorEnd> y B fin")]
    [InlineData("Texto <UIColor:f20100>A<UIColorEnd> y B fin")]
    [InlineData("Texto <UIColor:f201ff>A<UIColorEnd> y B fin")]
    [InlineData("Texto <UIColor:f201f6>A<UIColorEnd> y <ColorType>B<EdgeColorType#2> fin")]
    public void InvalidOwnColours_AreRejectedByValidatorAndTree(string target)
    {
        var report = SeStringCompatibilityValidator.Validate(TwoSpanSource, target);
        Assert.False(report.IsCompatible);
        Assert.False(SeStringTree.TryTranslate(TwoSpanVanilla(), TwoSpanSource, target, out _, out _));
    }

    [Fact]
    public void MalformedOwnColourToken_IsAStrayDelimiter()
    {
        var report = SeStringCompatibilityValidator.Validate(TwoSpanSource, "Texto <UIColor:zz01f6>A<UIColorEnd> y B fin");
        Assert.False(report.IsCompatible);
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.StrayDelimiter);
    }

    [Fact]
    public void OutOfRangeCode_ReportsInvalidOwnColor()
    {
        var report = SeStringCompatibilityValidator.Validate(TwoSpanSource, "Texto <UIColor:f2023b>A<UIColorEnd> y B fin");
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.InvalidOwnColor);
    }

    [Fact]
    public void OwnColourInsideARun_IsRejected()
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

        var target = "<Run>x<NewLine><UIColor:f201f6>y<UIColorEnd><RunEnd>";
        var report = SeStringCompatibilityValidator.Validate(source, target);
        Assert.False(report.IsCompatible);
        Assert.Contains(report.Violations, v => v.Kind == SeStringViolationKind.InvalidOwnColor);
        Assert.False(SeStringTree.TryTranslate(vanilla, source, target, out _, out _));
    }

    [Fact]
    public void UpperCaseHex_IsAccepted()
    {
        var vanilla = Text("Hola mundo");
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        var target = "Hola <UIColor:F201FA>mundo<UIColorEnd>";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(Join(Text("Hola "), Open(0xFA), Text("mundo"), Close), result);
    }

    [Fact]
    public void SuppressedNewLine_AfterAnOwnColourClose_IsAccepted_AndSpacesCorrectly()
    {
        var vanilla = Join(Text("A"), NewLineBytes, Text("B"));
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        var marker = SeStringSuppressedNewLine.Marker.ToString();

        // NewLine glued to the close of an own colour is a style-glued NewLine: suppressible.
        var target = "<UIColor:f201f6>A<UIColorEnd><NewLine>" + marker + "B";
        Assert.True(SeStringCompatibilityValidator.Validate(source, target).IsCompatible);
        Assert.True(SeStringTree.TryTranslate(vanilla, source, target, out var result, out var reason), reason);
        Assert.Equal(Join(Open(0xF6), Text("A"), Close, Text(" B")), result);

        // Pending space is released before an own colour token.
        var before = "A<NewLine>" + marker + "<UIColor:f201f6>B<UIColorEnd>";
        Assert.True(SeStringTree.TryTranslate(vanilla, source, before, out var spaced, out var reason2), reason2);
        Assert.Equal(Join(Text("A "), Open(0xF6), Text("B"), Close), spaced);
    }

    [Fact]
    public void FlatPaths_RefuseATargetWithOwnColours()
    {
        var vanilla = Join(Text("Hola "), Open(0xF4), Text("mundo"), Close);
        var segments = SeStringParser.Parse(vanilla);
        var source = SeStringTokenizer.Tokenize(segments).Text;
        var target = "Hola <UIColor:f201f6>mundo<UIColorEnd>";

        Assert.False(SeStringParser.TryReplaceTokenized(segments, source, target, out _, out _));
        Assert.False(SeStringParser.TryReplace(segments, "Hola", "Ho<UIColor:f201f6>la", out _, out _));
    }

    [Fact]
    public void StandardMacroTargetOnPlainSource_NeverWritesOwnColourTagsAsText()
    {
        var vanilla = Text("Hola mundo");
        var source = SeStringTreeTokenizer.TokenizeRawText(vanilla);
        var target = "<UIColor:f201f6>Hola<UIColorEnd> <Gender>a<GenderElse>o<GenderEnd>";

        Assert.False(SeStringTree.TryTranslate(vanilla, source, target, out _, out _));
    }

    [Fact]
    public void ManifestGate_ValidatesPlainSourcesThatCarryOwnColours()
    {
        Assert.Empty(ManifestSeStringGate.Check([Entry("Hola mundo", "Hola <UIColor:f201f6>mundo<UIColorEnd>")]));

        var violation = Assert.Single(ManifestSeStringGate.Check([Entry("Hola mundo", "Hola <UIColor:f201f6>mundo")]));
        Assert.Contains(violation.Report.Violations, v => v.Kind == SeStringViolationKind.InvalidOwnColor);
    }

    [Fact]
    public void OwnColors_Bytes_AreTheGameEncoding()
    {
        Assert.True(SeStringOwnColors.TryGetBytes(true, "f201f6", out var open));
        Assert.Equal(Open(0xF6), open);
        Assert.True(SeStringOwnColors.TryGetBytes(false, string.Empty, out var close));
        Assert.Equal(Close, close);
        Assert.False(SeStringOwnColors.TryGetBytes(true, "f201ff", out _));
        Assert.False(SeStringOwnColors.TryGetBytes(true, "f2023b", out _));
        Assert.False(SeStringOwnColors.TryGetBytes(true, "f2017f", out _));
    }

    private static TranslationEntry Entry(string source, string target) => new()
    {
        Source = source,
        Target = target,
        Status = TranslationEntryStatus.Approved,
        SourceKey = new TranslationSourceKey
        {
            Sheet = "GuidePageString",
            RowId = 1,
            Field = "Column0",
            ExdPath = "exd/guidepagestring_0_ja.exd",
        },
    };
}
