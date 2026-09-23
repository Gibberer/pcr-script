using System.Diagnostics;
using System.Text;
using System.Windows;
using System.Windows.Interop;

namespace PcrDesktop
{
    internal static class WindowsCompatibility
    {
        // Match Windows CommandLineToArgvW / CRT quoting, including trailing slashes.
        internal static string QuoteArgument(string value)
        {
            var result = new StringBuilder("\"");
            int slashes = 0;
            foreach (char character in value)
            {
                if (character == '\\') { slashes++; continue; }
                result.Append('\\', character == '"' ? slashes * 2 + 1 : slashes);
                result.Append(character);
                slashes = 0;
            }
            return result.Append('\\', slashes * 2).Append('"').ToString();
        }

        internal static async Task WaitForExitAsync(this Process process, CancellationToken token = default)
        {
            var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            EventHandler exited = (_, _) => completion.TrySetResult(true);
            process.EnableRaisingEvents = true;
            process.Exited += exited;
            try
            {
                if (process.HasExited) return;
                using (token.Register(() => completion.TrySetCanceled()))
                    await completion.Task;
            }
            finally { process.Exited -= exited; }
        }

        internal static void KillTree(Process process)
        {
            if (process.HasExited) return;
            using var killer = Process.Start(new ProcessStartInfo
            {
                FileName = System.IO.Path.Combine(Environment.SystemDirectory, "taskkill.exe"),
                Arguments = $"/PID {process.Id} /T /F", UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true
            });
            if (killer is null || !killer.WaitForExit(10000))
                throw new InvalidOperationException("辅助进程终止未确认，请检查运行状态");
            if (!process.WaitForExit(5000))
                throw new InvalidOperationException("辅助进程终止未确认：" + killer.StandardError.ReadToEnd());
        }

        internal static TValue GetValueOrDefault<TKey, TValue>(this Dictionary<TKey, TValue> values, TKey key, TValue fallback)
            => values.TryGetValue(key, out var value) ? value : fallback;

        internal static void Deconstruct<TKey, TValue>(this KeyValuePair<TKey, TValue> pair, out TKey key, out TValue value)
        { key = pair.Key; value = pair.Value; }
    }

    internal sealed class OpenFolderDialog
    {
        public string Title { get; set; } = "选择目录";
        public string FolderName { get; private set; } = "";
        private sealed class Owner(IntPtr handle) : System.Windows.Forms.IWin32Window
        { public IntPtr Handle { get; } = handle; }

        public bool? ShowDialog(Window owner)
        {
            using var dialog = new System.Windows.Forms.FolderBrowserDialog { Description = Title };
            if (dialog.ShowDialog(new Owner(new WindowInteropHelper(owner).Handle)) != System.Windows.Forms.DialogResult.OK)
                return false;
            FolderName = dialog.SelectedPath;
            return true;
        }
    }
}

namespace System.Runtime.CompilerServices
{
    internal static class IsExternalInit { }
}
