using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Threading;

namespace LocalSearchLauncher;

/// <summary>macOSネイティブ版と同じ検索・ganttメモ・結果アクションを提供する。</summary>
public partial class MainWindow : Window
{
    private readonly LauncherApiClient _api = new();
    private readonly Action _hide;
    private readonly DispatcherTimer _debounce = new() { Interval = TimeSpan.FromMilliseconds(180) };
    private CancellationTokenSource? _searchCancellation;
    private int _ganttParent = ReadNonNegativeInt("LAUNCHER_GANTT_PARENT", 0);
    private bool _memoActive;
    private bool _hasActivated;
    private bool _arrowNavigated;
    internal bool AllowClose { get; set; }
    /// <summary>再表示時にも検索語と拡張子フィルタを維持するための画面状態を返す。</summary>
    internal LauncherWindowState CaptureState() => new(
        QueryBox.Text,
        ExtensionBox.Text,
        MemoTitle.Text,
        MemoBody.Text,
        _memoActive,
        GanttCheck.IsChecked == true
    );

    internal MainWindow(Action hide, LauncherWindowState state, string hotkeyDisplayName)
    {
        InitializeComponent();
        _hide = hide;
        _debounce.Tick += async (_, _) => { _debounce.Stop(); await SearchAsync(); };
        Activated += (_, _) => _hasActivated = true;
        Deactivated += (_, _) => { if (_hasActivated) _hide(); };
        Closing += (_, e) => { if (!AllowClose) { e.Cancel = true; _hide(); } };
        QueryBox.Text = state.Query;
        ExtensionBox.Text = state.ExtensionFilter;
        MemoTitle.Text = state.MemoTitle;
        MemoBody.Text = state.MemoBody;
        GanttCheck.IsChecked = state.IncludeGantt;
        _memoActive = state.MemoActive;
        SearchView.Visibility = _memoActive ? Visibility.Collapsed : Visibility.Visible;
        MemoView.Visibility = _memoActive ? Visibility.Visible : Visibility.Collapsed;
        Status.Text = $"{hotkeyDisplayName}　Tabでganttメモ　Escで閉じる";
        ParentLabel.Text = $"parent: {_ganttParent}";
    }

    internal void ShowAndActivate()
    {
        Show();
        var handle = new WindowInteropHelper(this).Handle;
        ShowWindow(handle, 9);
        SetForegroundWindow(handle);
        Activate();
        FocusActiveView();
    }

    private void FocusActiveView()
    {
        if (_memoActive) { MemoTitle.Focus(); MemoTitle.SelectAll(); }
        else { QueryBox.Focus(); QueryBox.SelectAll(); }
    }

    private void QueryBox_TextChanged(object sender, TextChangedEventArgs e)
    { _arrowNavigated = false; _debounce.Stop(); _debounce.Start(); }

    private async Task SearchAsync()
    {
        var query = QueryBox.Text.Trim();
        if (query.Length == 0) { Results.ItemsSource = null; Status.Text = "検索語を入力してください　Tabでganttメモ"; return; }
        _searchCancellation?.Cancel();
        _searchCancellation?.Dispose();
        _searchCancellation = new CancellationTokenSource();
        try
        {
            Status.Text = "検索中…";
            var limit = ReadNonNegativeInt("LAUNCHER_SEARCH_LIMIT", 8);
            var response = await _api.SearchAsync(query, Math.Max(1, limit), GanttCheck.IsChecked == true, ExtensionBox.Text.Trim(), _searchCancellation.Token);
            Results.ItemsSource = response.Items;
            Results.SelectedIndex = response.Items.Count > 0 ? 0 : -1;
            Status.Text = $"{response.Total} 件　Enterで開く　Tabでganttメモ";
        }
        catch (OperationCanceledException) { }
        catch (Exception error) { Status.Text = $"検索に失敗しました: {error.Message}"; }
    }

    private void GanttCheck_Click(object sender, RoutedEventArgs e)
    { _debounce.Stop(); _debounce.Start(); QueryBox.Focus(); }

    private void Window_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            e.Handled = true;
            if (_memoActive) SwitchView(false); else _hide();
            return;
        }
        if (e.Key == Key.Tab)
        {
            e.Handled = true;
            MoveTabFocus(Keyboard.Modifiers.HasFlag(ModifierKeys.Shift));
            return;
        }
        if (!_memoActive && e.Key is Key.Down or Key.Up)
        { e.Handled = true; MoveSelection(e.Key == Key.Down ? 1 : -1); return; }
        if (!_memoActive && e.Key == Key.Return && _arrowNavigated)
        { e.Handled = true; _ = OpenSelectedAsync(); }
    }

    private void MoveSelection(int delta)
    {
        if (Results.Items.Count == 0) return;
        var current = Results.SelectedIndex < 0 ? 0 : Results.SelectedIndex;
        Results.SelectedIndex = (current + delta + Results.Items.Count) % Results.Items.Count;
        Results.ScrollIntoView(Results.SelectedItem);
        _arrowNavigated = true;
    }

    private async Task OpenSelectedAsync()
    {
        if (Results.SelectedItem is SearchItem item) await OpenItemAsync(item);
    }

    private async Task OpenItemAsync(SearchItem item)
    {
        try
        {
            if (item.IsGantt) await _api.OpenGanttTaskAsync(item.FileId);
            else
            {
                var clickTask = _api.RecordClickAsync(item, QueryBox.Text.Trim());
                if (UsesSystemFileLauncher(item.FullPath)) OpenFileWithSystemDefault(item.FullPath);
                else OpenUrl(PrimaryUrl(item));
                try { await clickTask; } catch { }
            }
            _hide();
        }
        catch (Exception error) { Status.Text = $"結果を開けません: {error.Message}"; }
    }

    private async void Results_MouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (FindAncestor<Button>(e.OriginalSource as DependencyObject) is not null) return;
        await OpenSelectedAsync();
    }
    private async void Reveal_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as FrameworkElement)?.DataContext is not SearchItem item) return;
        var target = item.ResultKind == "folder" ? item.FullPath : ParentPath(item.FullPath);
        try { await _api.OpenLocationAsync(target); } catch (Exception error) { Status.Text = $"保存場所を開けません: {error.Message}"; }
    }
    private void CopyPath_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as FrameworkElement)?.DataContext is not SearchItem item) return;
        try { Clipboard.SetText(item.FullPath); Status.Text = "クリップボードにコピーしました"; }
        catch (Exception error) { Status.Text = $"クリップボードへコピーできません: {error.Message}"; }
    }
    private void OpenFolder_Click(object sender, RoutedEventArgs e)
    { if ((sender as FrameworkElement)?.DataContext is SearchItem item) TryOpenUrl(FolderUrl(item)); }
    private void OpenGanttLink_Click(object sender, RoutedEventArgs e)
    { if ((sender as FrameworkElement)?.DataContext is SearchItem { GanttLink: not null } item) TryOpenUrl(item.GanttLink); }
    private void OpenGui_Click(object sender, RoutedEventArgs e) { if (TryOpenUrl($"{ApiBase()}/")) _hide(); }

    private void SwitchView(bool memo)
    {
        _memoActive = memo;
        SearchView.Visibility = memo ? Visibility.Collapsed : Visibility.Visible;
        MemoView.Visibility = memo ? Visibility.Visible : Visibility.Collapsed;
        if (memo) _ = RefreshParentAsync();
        FocusActiveView();
    }

    /// <summary>検索欄、拡張子欄、ganttメモ主要入力をTab/Shift+Tabで循環する。</summary>
    private void MoveTabFocus(bool backwards)
    {
        if (!_memoActive)
        {
            if (backwards && ExtensionBox.IsKeyboardFocusWithin) QueryBox.Focus();
            else if (backwards) { SwitchView(true); MemoSubmit.Focus(); }
            else if (QueryBox.IsKeyboardFocusWithin) ExtensionBox.Focus();
            else SwitchView(true);
            return;
        }
        if (MemoTitle.IsKeyboardFocusWithin)
        {
            if (backwards) { SwitchView(false); ExtensionBox.Focus(); }
            else MemoBody.Focus();
        }
        else if (MemoBody.IsKeyboardFocusWithin)
        {
            if (backwards) MemoTitle.Focus(); else MemoSubmit.Focus();
        }
        else if (MemoSubmit.IsKeyboardFocusWithin)
        {
            if (backwards) MemoBody.Focus(); else { SwitchView(false); QueryBox.Focus(); }
        }
        else MemoTitle.Focus();
    }

    private async Task RefreshParentAsync()
    {
        try { _ganttParent = await _api.GetGanttParentAsync(_ganttParent); }
        catch { }
        ParentLabel.Text = $"parent: {_ganttParent}";
    }

    private async void MemoSubmit_Click(object sender, RoutedEventArgs e)
    {
        var title = MemoTitle.Text.Trim();
        if (title.Length == 0) { MemoStatus.Text = "タスク名を入力してください"; MemoTitle.Focus(); return; }
        MemoSubmit.IsEnabled = false;
        try
        {
            await RefreshParentAsync();
            await _api.CreateGanttTaskAsync(GanttTaskBuilder.Build(title, MemoBody.Text, _ganttParent));
            MemoTitle.Clear(); MemoBody.Clear();
            MemoStatus.Text = "gantt に追加しました";
            MemoTitle.Focus();
        }
        catch (Exception error) { MemoStatus.Text = $"gantt 追加に失敗しました: {error.Message}"; }
        finally { MemoSubmit.IsEnabled = true; }
    }
    private void MemoCancel_Click(object sender, RoutedEventArgs e) => SwitchView(false);

    private string PrimaryUrl(SearchItem item) => item.IsWeb
        ? item.FullPath
        : item.ResultKind == "folder" ? $"{WebBase()}/?path={Uri.EscapeDataString(item.FullPath)}" : $"{WebBase()}/api/fullpath?path={Uri.EscapeDataString(item.FullPath)}";
    private string FolderUrl(SearchItem item) => $"{WebBase()}/?path={Uri.EscapeDataString(item.ResultKind == "folder" ? item.FullPath : ParentPath(item.FullPath))}";
    private static string ParentPath(string path) => Path.GetDirectoryName(path) ?? path;
    private static string WebBase() => LauncherUrls.OpenHubBase();
    private static string ApiBase() => (Environment.GetEnvironmentVariable("LAUNCHER_API_BASE_URL") ?? "http://127.0.0.1:8079").TrimEnd('/');
    private static void OpenUrl(string url) => Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
    private static bool UsesSystemFileLauncher(string path) => new[] { ".py", ".bat", ".exe", ".lnk" }.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase);
    /// <summary>スクリプト・実行ファイル・ショートカットを親フォルダをcurrent dirとして起動する。</summary>
    private static void OpenFileWithSystemDefault(string path) => Process.Start(new ProcessStartInfo(path)
    {
        UseShellExecute = true,
        WorkingDirectory = Path.GetDirectoryName(path) ?? Environment.CurrentDirectory,
    });
    private bool TryOpenUrl(string url)
    {
        try { OpenUrl(url); return true; }
        catch (Exception error) { Status.Text = $"リンクを開けません: {error.Message}"; return false; }
    }
    private static int ReadNonNegativeInt(string name, int fallback) => int.TryParse(Environment.GetEnvironmentVariable(name), out var value) && value >= 0 ? value : fallback;
    private static T? FindAncestor<T>(DependencyObject? current) where T : DependencyObject
    {
        while (current is not null)
        {
            if (current is T match) return match;
            current = System.Windows.Media.VisualTreeHelper.GetParent(current);
        }
        return null;
    }

    protected override void OnClosed(EventArgs e)
    {
        _debounce.Stop();
        _searchCancellation?.Cancel();
        _searchCancellation?.Dispose();
        _api.Dispose();
        base.OnClosed(e);
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr hWnd);
    [System.Runtime.InteropServices.DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr hWnd, int command);
}
