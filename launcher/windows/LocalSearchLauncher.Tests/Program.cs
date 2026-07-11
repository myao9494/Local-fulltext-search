using LocalSearchLauncher;

/// <summary>外部テストパッケージなしでWPF共有ロジックの契約を検証する。</summary>
static void Assert(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}

var task = GanttTaskBuilder.Build(" 仕様確認 ", " メモ ", 12, new DateOnly(2026, 7, 11));
Assert(task.Text == "仕様確認", "タスク名をtrimする");
Assert(task.Memo == "メモ", "メモをtrimする");
Assert(task.StartDate == "2026-07-11 00:00:00", "開始日は当日0時");
Assert(task.EndDate == "2026-07-12 00:00:00", "終了日は翌日0時");
Assert(task.Progress == 0.1 && task.Parent == 12 && task.KindTask == 1, "macOS版と同じ既定値");

var gantt = new SearchItem(-9, "file", "gantt", "", "task", "gantt://tasks/9", "", "&lt;b&gt;memo&lt;/b&gt;", "https://example.test");
Assert(gantt.IsGantt && !gantt.IsLocal && gantt.HasGanttLink, "gantt結果を判定する");
Assert(gantt.PlainSnippet == "<b>memo</b>", "HTMLエンティティを復元する");

var state = new LauncherWindowState("query", "title", "body", true, true);
Assert(state.MemoActive && state.IncludeGantt && state.MemoTitle == "title", "ウィンドウ再生成用の入力状態を保持する");

Environment.SetEnvironmentVariable("LAUNCHER_WEB_BASE_URL", "http://127.0.0.1:8123/");
Assert(LauncherUrls.OpenHubBase() == "http://127.0.0.1:8123", "結果openは設定済みの外部Openハブを使う");
Environment.SetEnvironmentVariable("LAUNCHER_WEB_BASE_URL", null);

Console.WriteLine("LocalSearchLauncher tests passed");
