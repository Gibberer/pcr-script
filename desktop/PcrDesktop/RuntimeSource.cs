using System.IO;

namespace PcrDesktop;

/// <summary>Download only the files needed by the Python runtime.</summary>
public static class RuntimeSource
{
    private const string Patterns = "/pcrscript/\n/images/\n/requirements.txt\n";

    public static async Task Download(string repository, string branch, string target, Action<string>? log = null,
        bool coreOnly = true)
    {
        target = Path.GetFullPath(target);
        if (File.Exists(target) || (Directory.Exists(target) && Directory.EnumerateFileSystemEntries(target).Any()))
            throw new IOException("目标目录已有文件，请选择空目录");
        var parent = Path.GetDirectoryName(target) ?? throw new IOException("不能使用磁盘根目录");
        Directory.CreateDirectory(parent);
        await Backend.Command("git", ["check-ref-format", "--branch", branch], parent);
        if (!coreOnly)
        {
            await Backend.Command("git", ["clone", "--branch", branch, "--", repository, target],
                parent, log: log, timeoutSeconds: 600);
            Validate(target);
            return;
        }
        // No initial checkout: otherwise clone downloads every blob before sparsity applies.
        await Backend.Command("git", ["clone", "--filter=blob:none", "--depth=1", "--no-checkout",
            "--single-branch", "--branch", branch, "--", repository, target], parent, log: log, timeoutSeconds: 600);
        await Backend.Command("git", ["sparse-checkout", "set", "--no-cone", "--stdin"], target, Patterns, log);
        await Backend.Command("git", ["checkout", branch], target, log: log, timeoutSeconds: 600);
        // The repository .gitignore is intentionally outside the download allowlist.
        File.AppendAllText(Path.Combine(target, ".git", "info", "exclude"),
            "\n/cache/\n/.venv/\n/daily_config.yml\n/daily_config.yml.bak\n*.pyc\n__pycache__/\n");
        Validate(target);
    }

    private static void Validate(string target)
    {
        if (!SetupWindow.IsProject(target) || !File.Exists(Path.Combine(target, "pcrscript", "desktop.py")))
            throw new IOException("下载的分支缺少新版 GUI 运行接口，请选择包含该接口的分支");
    }
}
