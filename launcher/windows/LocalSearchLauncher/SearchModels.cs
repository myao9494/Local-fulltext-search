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
    public string IconPath => $"Assets/catppuccin/{CatppuccinIconName()}.png";

    /// <summary>検索結果の種別・拡張子から同梱 Catppuccin PNG 名を返す。</summary>
    private string CatppuccinIconName()
    {
        if (IsGantt) return "task";
        if (SourceType == "web") return "html";
        if (ResultKind == "folder") return "folder";
        return Path.GetExtension(FileName).ToLowerInvariant() switch
        {
            ".md" or ".markdown" => "markdown", ".pdf" => "pdf", ".json" => "json", ".xml" => "xml",
            ".txt" => "txt", ".csv" => "csv", ".yaml" or ".yml" => "yaml", ".zip" => "zip",
            ".html" or ".htm" => "html", ".js" or ".jsx" => "javascript", ".ts" or ".tsx" => "typescript", ".py" => "python",
            ".excalidraw" => "excalidraw", ".dio" or ".drawio" => "drawio", ".epub" => "epub",
            ".png" or ".jpg" or ".jpeg" or ".gif" or ".svg" or ".webp" => "image",
            ".mp3" or ".wav" or ".m4a" => "audio", ".mp4" or ".mov" or ".avi" => "video", _ => "file",
        };
    }
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
