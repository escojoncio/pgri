namespace XivSpanish.GameData;

/// <summary>
/// Target-authored colour spans: the Spanish text carries ITS OWN colour where the French puts it,
/// instead of inheriting (count, order and colour code) the colour macros of the Japanese source.
///
/// <para>Syntax (target only, never in a source): <c>&lt;UIColor:f201f6&gt;text&lt;UIColorEnd&gt;</c>.
/// The code is 6 hex digits <c>f201yy</c> with <c>yy</c> in <c>0x80..0xFE</c> (UIColor row
/// <c>0x0180..0x01FE</c>: colour AND edge colour, edge = code + 1, both encode as leaf macros without a NUL
/// byte). The open token is rebuilt as the two macros the game uses:
/// <c>02 48 04 F2 01 yy 03</c> (ColorType) + <c>02 49 04 F2 01 yy+1 03</c> (EdgeColorType); the close token as
/// <c>02 49 02 01 03</c> + <c>02 48 02 01 03</c> (reset of both).</para>
///
/// <para>Rules (identical in the Python emulation, <c>sestring.py</c>): when a target carries at least one own
/// colour token, the source's <c>&lt;ColorType&gt;</c>/<c>&lt;EdgeColorType&gt;</c> tokens are IGNORED (not required) and the target must
/// not carry any; spans do not nest and must be closed; only flat strings (no <c>&lt;Run&gt;</c>/<c>&lt;MacroEnd&gt;</c>); only the
/// run-aware tree path understands them (flat paths and empty-column writes refuse). Without own colour tokens
/// everything behaves exactly as before.</para>
/// </summary>
public static class SeStringOwnColors
{
    /// <summary>Prefix of the open token, <c>&lt;UIColor:</c> (9 chars); the token is 16 chars long.</summary>
    public const string OpenPrefix = "<UIColor:";

    /// <summary>The close token.</summary>
    public const string CloseToken = "<UIColorEnd>";

    /// <summary>Base name of the open token (as seen by the validator).</summary>
    public const string OpenBaseName = "UIColor";

    /// <summary>Base name of the close token.</summary>
    public const string CloseBaseName = "UIColorEnd";

    private const int OpenTokenLength = 16;
    private const int HexLength = 6;

    /// <summary>Cheap textual test (may be a false positive for an escaped literal): flat paths refuse such targets.</summary>
    public static bool ContainsOwnColor(string text)
        => text.Contains(OpenPrefix, StringComparison.Ordinal)
           || text.Contains(CloseToken, StringComparison.Ordinal);

    /// <summary>True for the base names of the two own-colour tokens.</summary>
    public static bool IsOwnColorBaseName(string baseName)
        => baseName == OpenBaseName || baseName == CloseBaseName;

    /// <summary>True for the base names of the source tokens that own colours replace.</summary>
    public static bool IsReplacedBaseName(string baseName)
        => baseName == "ColorType" || baseName == "EdgeColorType";

    /// <summary>
    /// Matches an own-colour token at <paramref name="index"/>: <c>&lt;UIColor:hhhhhh&gt;</c> (any 6 hex digits) or
    /// <c>&lt;UIColorEnd&gt;</c>. Syntax only; <see cref="TryGetBytes"/> checks the code range.
    /// </summary>
    public static bool TryMatchAt(string text, int index, out string token, out bool isOpen, out string hex)
    {
        token = string.Empty;
        hex = string.Empty;
        isOpen = false;

        if (index < 0 || index >= text.Length || text[index] != '<')
        {
            return false;
        }

        if (string.CompareOrdinal(text, index, CloseToken, 0, CloseToken.Length) == 0)
        {
            token = CloseToken;
            return true;
        }

        if (index + OpenTokenLength > text.Length
            || string.CompareOrdinal(text, index, OpenPrefix, 0, OpenPrefix.Length) != 0
            || text[index + OpenTokenLength - 1] != '>')
        {
            return false;
        }

        for (var k = 0; k < HexLength; k++)
        {
            if (!char.IsAsciiHexDigit(text[index + OpenPrefix.Length + k]))
            {
                return false;
            }
        }

        hex = text.Substring(index + OpenPrefix.Length, HexLength).ToLowerInvariant();
        token = text.Substring(index, OpenTokenLength);
        isOpen = true;
        return true;
    }

    /// <summary>
    /// The bytes an own-colour token is rebuilt to (two concatenated macros), or false when the open code is outside
    /// <c>f201yy</c>, <c>yy</c> in <c>0x80..0xFE</c>.
    /// </summary>
    public static bool TryGetBytes(bool isOpen, string hex, out byte[] bytes)
    {
        if (!isOpen)
        {
            bytes = [0x02, 0x49, 0x02, 0x01, 0x03, 0x02, 0x48, 0x02, 0x01, 0x03];
            return true;
        }

        bytes = [];
        if (hex.Length != HexLength || !hex.StartsWith("f201", StringComparison.Ordinal))
        {
            return false;
        }

        if (!byte.TryParse(hex.AsSpan(4, 2), System.Globalization.NumberStyles.AllowHexSpecifier, System.Globalization.CultureInfo.InvariantCulture, out var code)
            || code < 0x80
            || code > 0xFE)
        {
            return false;
        }

        bytes = [0x02, 0x48, 0x04, 0xF2, 0x01, code, 0x03, 0x02, 0x49, 0x04, 0xF2, 0x01, (byte)(code + 1), 0x03];
        return true;
    }
}
