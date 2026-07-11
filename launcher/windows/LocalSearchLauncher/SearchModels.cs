using System.Net;
using System.Text.RegularExpressions;

namespace LocalSearchLauncher;

/// <summary>検索APIのJSONレスポンスを表す。</summary>
internal sealed record SearchResponse(int Total, List<SearchItem> Items, bool HasMore);

internal sealed record SearchItem(
    int FileId, string ResultKind, string SourceType, string TargetPath,
    string FileName, string FullPath, string FileExt, string Snippet, string? GanttLink)
{
    /// <summary>HTML断片をランチャー表示用のプレーンテキストへ変換する。</summary>
    public string PlainSnippet => WebUtility.HtmlDecode(Regex.Replace(Snippet ?? "", "<[^>]+>", ""));
    public bool IsGantt => SourceType == "gantt";
    public bool IsLocal => !IsGantt;
    public bool HasGanttLink => !string.IsNullOrWhiteSpace(GanttLink);
}

internal sealed record GanttTaskRequest(
    string Text,
    string StartDate,
    string EndDate,
    double Progress,
    int Parent,
    int KindTask,
    string Memo);

internal sealed record LauncherWindowState(
    string Query = "",
    string MemoTitle = "",
    string MemoBody = "",
    bool MemoActive = false,
    bool IncludeGantt = false);

/// <summary>Open/UIハブの設定値を全WPF画面で一貫して組み立てる。</summary>
internal static class LauncherUrls
{
    public static string OpenHubBase() =>
        (Environment.GetEnvironmentVariable("LAUNCHER_WEB_BASE_URL") ?? "http://127.0.0.1:8001").TrimEnd('/');
}

/// <summary>macOS版と同じganttタスク作成値を組み立てる。</summary>
internal static class GanttTaskBuilder
{
    public static GanttTaskRequest Build(string title, string memo, int parent, DateOnly? today = null)
    {
        var start = today ?? DateOnly.FromDateTime(DateTime.Today);
        return new(
            title.Trim(),
            $"{start:yyyy-MM-dd} 00:00:00",
            $"{start.AddDays(1):yyyy-MM-dd} 00:00:00",
            0.1,
            Math.Max(0, parent),
            1,
            memo.Trim());
    }
}
