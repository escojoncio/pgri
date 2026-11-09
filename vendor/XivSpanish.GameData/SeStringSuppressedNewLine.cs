namespace XivSpanish.GameData;

/// <summary>
/// Explicit "turn this fixed line break into a space" mark for translated targets.
///
/// <para>A target may place the private-use character <see cref="Marker"/> (U+E0F0) IMMEDIATELY after
/// a <c>&lt;NewLine&gt;</c> / <c>&lt;NewLine#N&gt;</c> token (for example
/// <c>Hola&lt;NewLine&gt;mundo</c>). The detokenizer then drops that NewLine and the marker and
/// lets the client wrap the text by itself. The NewLine token stays in the target string, so the
/// token multiset, order and count validated against the source do not change; only the bytes
/// written differ. The marker is NEVER written to the game: the detokenizer consumes it, rejects a
/// stray one, and every flat (non run-aware) path refuses a target that carries it.</para>
///
/// <para>Space rule (identical in the Python emulation, <c>sestring.aplicar_marcas</c>): a suppressed
/// NewLine sets a "pending space". The pending space is written as a single ' ' right before the next
/// literal character or the next non-NewLine token, unless the text written so far already ends with
/// a space or that next character is itself a space. It is dropped when the next thing is another
/// NewLine (marked or not) or the end of the string, so an empty marked chunk means "nothing".</para>
///
/// <para>Hard newlines can never be suppressed (the validator rejects the mark): inside a
/// <c>&lt;Run&gt;</c> or inside a macro bracket (the tree detokenizer's stack; same rule as extra NewLines), at the
/// start of the string, or glued to a preceding NewLine or non-style token. A NewLine glued to a
/// colour/style token (ColorType, EdgeColorType, Color, EdgeColor, Italic, Edge) can be suppressed,
/// and so can the last NewLine of the string (its pending space is dropped).</para>
/// </summary>
public static class SeStringSuppressedNewLine
{
    /// <summary>Reserved private-use character that follows a NewLine token to suppress it. Absent from the game's ja/fr text.</summary>
    public const char Marker = '';

    /// <summary>True when <paramref name="text"/> carries the suppression marker anywhere.</summary>
    public static bool ContainsMarker(string text) => text.Contains(Marker);
}
