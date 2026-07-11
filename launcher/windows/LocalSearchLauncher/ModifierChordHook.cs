using System.ComponentModel;
using System.Runtime.InteropServices;

namespace LocalSearchLauncher;

/// <summary>Windows + Alt が揃った瞬間を、通常入力を遮断せずに検出する。</summary>
internal sealed class ModifierChordHook : IDisposable
{
    private const int WhKeyboardLl = 13, WmKeyDown = 0x0100, WmKeyUp = 0x0101, WmSysKeyDown = 0x0104, WmSysKeyUp = 0x0105;
    private const uint VkLeftWin = 0x5B, VkRightWin = 0x5C, VkMenu = 0x12, VkLeftMenu = 0xA4, VkRightMenu = 0xA5;
    private readonly Action _activate;
    private readonly HookProcedure _procedure;
    private IntPtr _hook;
    private bool _windowsDown, _altDown, _activated;

    public ModifierChordHook(Action activate) { _activate = activate; _procedure = HookCallback; }
    public void Start()
    {
        _hook = SetWindowsHookEx(WhKeyboardLl, _procedure, GetModuleHandle(null), 0);
        if (_hook == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "Windows + Alt の監視を開始できません。");
    }
    private IntPtr HookCallback(int code, IntPtr wParam, IntPtr lParam)
    {
        if (code >= 0)
        {
            var key = Marshal.PtrToStructure<KeyboardHookData>(lParam).VirtualKey;
            var down = wParam.ToInt32() is WmKeyDown or WmSysKeyDown;
            var up = wParam.ToInt32() is WmKeyUp or WmSysKeyUp;
            if (key is VkLeftWin or VkRightWin) _windowsDown = down ? true : up ? false : _windowsDown;
            if (key is VkMenu or VkLeftMenu or VkRightMenu) _altDown = down ? true : up ? false : _altDown;
            if (_windowsDown && _altDown && !_activated) { _activated = true; _activate(); }
            if (!_windowsDown || !_altDown) _activated = false;
        }
        return CallNextHookEx(_hook, code, wParam, lParam);
    }
    public void Dispose() { if (_hook != IntPtr.Zero) { UnhookWindowsHookEx(_hook); _hook = IntPtr.Zero; } }
    private delegate IntPtr HookProcedure(int code, IntPtr wParam, IntPtr lParam);
    [StructLayout(LayoutKind.Sequential)] private readonly struct KeyboardHookData { public readonly uint VirtualKey, ScanCode, Flags, Time; public readonly IntPtr ExtraInfo; }
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr SetWindowsHookEx(int hookId, HookProcedure callback, IntPtr module, uint threadId);
    [DllImport("user32.dll", SetLastError = true)] private static extern bool UnhookWindowsHookEx(IntPtr hook);
    [DllImport("user32.dll")] private static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr wParam, IntPtr lParam);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr GetModuleHandle(string? moduleName);
}
