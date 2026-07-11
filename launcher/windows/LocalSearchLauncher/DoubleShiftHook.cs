using System.ComponentModel;
using System.Runtime.InteropServices;

namespace LocalSearchLauncher;

/// <summary>通常のキー入力を遮断せず、Shiftキーだけの素早い2回押下を検出する。</summary>
internal sealed class DoubleShiftHook : IDisposable
{
    private const int WhKeyboardLl = 13;
    private const int WmKeyDown = 0x0100;
    private const int WmKeyUp = 0x0101;
    private const int WmSysKeyDown = 0x0104;
    private const int WmSysKeyUp = 0x0105;
    private const uint VkShift = 0x10;
    private const uint VkLeftShift = 0xA0;
    private const uint VkRightShift = 0xA1;
    private const long DoubleTapMilliseconds = 400;
    private readonly Action _activate;
    private readonly HookProcedure _procedure;
    private IntPtr _hook;
    private bool _shiftDown;
    private long _firstTapReleasedAt;

    public DoubleShiftHook(Action activate)
    {
        _activate = activate;
        _procedure = HookCallback;
    }

    public void Start()
    {
        _hook = SetWindowsHookEx(WhKeyboardLl, _procedure, GetModuleHandle(null), 0);
        if (_hook == IntPtr.Zero)
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Shiftキーの2回押下監視を開始できません。");
    }

    private IntPtr HookCallback(int code, IntPtr wParam, IntPtr lParam)
    {
        if (code >= 0)
        {
            var key = Marshal.PtrToStructure<KeyboardHookData>(lParam).VirtualKey;
            var message = wParam.ToInt32();
            var isShift = key is VkShift or VkLeftShift or VkRightShift;
            if (!isShift && (message == WmKeyDown || message == WmSysKeyDown))
                _firstTapReleasedAt = 0;
            else if (isShift && (message == WmKeyDown || message == WmSysKeyDown) && !_shiftDown)
                _shiftDown = true;
            else if (isShift && (message == WmKeyUp || message == WmSysKeyUp) && _shiftDown)
            {
                _shiftDown = false;
                var now = Environment.TickCount64;
                if (_firstTapReleasedAt > 0 && now - _firstTapReleasedAt <= DoubleTapMilliseconds)
                {
                    _firstTapReleasedAt = 0;
                    _activate();
                }
                else
                {
                    _firstTapReleasedAt = now;
                }
            }
        }
        return CallNextHookEx(_hook, code, wParam, lParam);
    }

    public void Dispose()
    {
        if (_hook == IntPtr.Zero) return;
        UnhookWindowsHookEx(_hook);
        _hook = IntPtr.Zero;
    }

    private delegate IntPtr HookProcedure(int code, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    private readonly struct KeyboardHookData
    {
        public readonly uint VirtualKey;
        public readonly uint ScanCode;
        public readonly uint Flags;
        public readonly uint Time;
        public readonly IntPtr ExtraInfo;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetWindowsHookEx(int hookId, HookProcedure callback, IntPtr module, uint threadId);
    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnhookWindowsHookEx(IntPtr hook);
    [DllImport("user32.dll")]
    private static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr wParam, IntPtr lParam);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr GetModuleHandle(string? moduleName);
}
