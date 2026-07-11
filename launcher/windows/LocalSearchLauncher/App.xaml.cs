using System.Threading;
using System.Windows;

namespace LocalSearchLauncher;

/// <summary>単一プロセスとグローバルホットキーを管理する。</summary>
public partial class App : Application
{
    private Mutex? _mutex;
    private DoubleShiftHook? _doubleShift;
    private MainWindow? _window;
    private LauncherWindowState _windowState = new();

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        _mutex = new Mutex(true, "LocalFulltextSearch.WpfLauncher", out var created);
        if (!created) { Shutdown(); return; }

        try
        {
            _doubleShift = new DoubleShiftHook(ToggleWindow);
            _doubleShift.Start();
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Local Search Launcher", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(1);
        }
    }

    /// <summary>
    /// 非表示後のウィンドウは破棄し、次回ホットキー時の仮想デスクトップ上でHWNDを作り直す。
    /// </summary>
    private void ToggleWindow()
    {
        Dispatcher.Invoke(() =>
        {
            if (_window is { IsVisible: true }) { HideAndDisposeWindow(); return; }
            HideAndDisposeWindow();
            _window = new MainWindow(HideAndDisposeWindow, _windowState, "Shift × 2");
            _window.ShowAndActivate();
        });
    }

    private void HideAndDisposeWindow()
    {
        if (_window is null) return;
        var old = _window;
        _windowState = old.CaptureState();
        _window = null;
        old.AllowClose = true;
        old.Close();
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _doubleShift?.Dispose();
        _mutex?.Dispose();
        base.OnExit(e);
    }
}
