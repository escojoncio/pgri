using Avalonia.Media;
using FFXIVSpanishPatcher.Pipeline;

namespace FFXIVSpanishPatcher.App.ViewModels;

/// <summary>One rendered console line built from a <see cref="PipelineEvent"/>: a timestamped,
/// component-tagged string colored by severity, matching the mockup's console.</summary>
public sealed class ConsoleLine
{
    private static readonly IBrush MutedBrush = new SolidColorBrush(Color.Parse("#77737F"));
    private static readonly IBrush PipelineBrush = new SolidColorBrush(Color.Parse("#FF8A3D"));
    private static readonly IBrush ExtractorBrush = new SolidColorBrush(Color.Parse("#C4A3FF"));
    private static readonly IBrush PatcherBrush = new SolidColorBrush(Color.Parse("#7DD3FC"));
    private static readonly IBrush PackagerBrush = new SolidColorBrush(Color.Parse("#FFC857"));
    private static readonly IBrush VerifierBrush = new SolidColorBrush(Color.Parse("#4ADE9A"));
    private static readonly IBrush DebugBrush = new SolidColorBrush(Color.Parse("#7D8695"));
    private static readonly IBrush InfoBrush = new SolidColorBrush(Color.Parse("#C9C5CF"));
    private static readonly IBrush OkBrush = new SolidColorBrush(Color.Parse("#4ADE9A"));
    private static readonly IBrush WarningBrush = new SolidColorBrush(Color.Parse("#FFC857"));
    private static readonly IBrush ErrorBrush = new SolidColorBrush(Color.Parse("#FF6B6B"));

    public ConsoleLine(PipelineEvent pipelineEvent)
    {
        var timestamp = DateTime.Now.ToString("HH:mm:ss");
        TimestampText = $"[{timestamp}] ";
        ComponentText = $"[{pipelineEvent.Component}] ";
        MessageText = pipelineEvent.Message;
        var count = pipelineEvent.Count is { } value ? $" ({value})" : string.Empty;

        CountText = count;
        Text = $"{TimestampText}{ComponentText}{MessageText}{CountText}";
        TimestampBrush = MutedBrush;
        ComponentBrush = ComponentBrushFor(pipelineEvent.Component);
        Foreground = BrushFor(pipelineEvent.Level);
    }

    public string TimestampText { get; }
    public string ComponentText { get; }
    public string MessageText { get; }
    public string CountText { get; }
    public string Text { get; }

    public IBrush TimestampBrush { get; }
    public IBrush ComponentBrush { get; }
    public IBrush Foreground { get; }

    private static IBrush BrushFor(PipelineLevel level) => level switch
    {
        PipelineLevel.Debug => DebugBrush,
        PipelineLevel.Ok => OkBrush,
        PipelineLevel.Warning => WarningBrush,
        PipelineLevel.Error => ErrorBrush,
        _ => InfoBrush,
    };

    private static IBrush ComponentBrushFor(PipelineComponent component) => component switch
    {
        PipelineComponent.Extractor => ExtractorBrush,
        PipelineComponent.Patcher => PatcherBrush,
        PipelineComponent.Packager => PackagerBrush,
        PipelineComponent.Verifier => VerifierBrush,
        _ => PipelineBrush,
    };
}
