using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace PcrDesktop;

// Invoked only by explicit smoke-test arguments, never by normal startup.
internal static class BootstrapChecks
{
    internal static void VerifyArchive(string workspace)
    {
        var root = Path.Combine(workspace, "cache", "desktop", "smoke", "archive-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var zip = Path.Combine(root, "safe.zip");
        using (var archive = ZipFile.Open(zip, ZipArchiveMode.Create))
        using (var writer = new StreamWriter(archive.CreateEntry("nested/sample.txt").Open())) writer.Write("synthetic");
        string digest;
        using (var sha = SHA256.Create()) using (var file = File.OpenRead(zip)) digest = BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "");
        PortableTools.VerifyHash(zip, digest);
        PortableTools.Extract(zip, Path.Combine(root, "safe"));
        if (File.ReadAllText(Path.Combine(root, "safe", "nested", "sample.txt")) != "synthetic") throw new IOException("ZIP 解压内容错误");
        var rejected = false;
        try { PortableTools.VerifyHash(zip, new string('0', 64)); } catch (IOException) { rejected = true; }
        if (!rejected) throw new IOException("错误校验值未被拒绝");
        foreach (var name in new[] { "../outside.txt", "nested/../../outside.txt", "C:/outside.txt", "nested/file:stream" })
        {
            var unsafeZip = Path.Combine(root, Guid.NewGuid() + ".zip");
            using (var archive = ZipFile.Open(unsafeZip, ZipArchiveMode.Create)) archive.CreateEntry(name);
            rejected = false;
            try { PortableTools.Extract(unsafeZip, Path.Combine(root, "unsafe")); } catch (IOException) { rejected = true; }
            if (!rejected || File.Exists(Path.Combine(root, "outside.txt"))) throw new IOException("ZIP 越界路径未被拒绝");
        }
    }

    internal static async Task Online(string root, string source)
    {
        root = Path.GetFullPath(root);
        Directory.CreateDirectory(root);
        using var writer = new StreamWriter(Path.Combine(root, "bootstrap.log")) { AutoFlush = true };
        void Log(string text) { lock (writer) writer.WriteLine(text); }
        var tools = Path.Combine(root, "tools");
        var python = await PortableTools.Ensure(PortableTools.Python, Log, tools);
        var git = await PortableTools.Ensure(PortableTools.Git, Log, tools);
        var adb = await PortableTools.Ensure(PortableTools.Adb, Log, tools);
        Log(await Backend.Command(git, ["--version"], root));
        Log(await Backend.Command(adb, ["version"], root)); // Does not enumerate or connect to a device.
        var originalPath = Environment.GetEnvironmentVariable("PATH");
        try
        {
            Environment.SetEnvironmentVariable("PATH", Environment.SystemDirectory);
            if (await PortableTools.EnsureGit(root, Log, tools) != git) throw new IOException("缺少系统 Git 时未使用便携工具");
        }
        finally { Environment.SetEnvironmentVariable("PATH", originalPath); }
        // Check cache reuse without making another request (the URL is deliberately unreachable).
        var cached = PortableTools.Python with { Url = "https://invalid.invalid/not-used" };
        if (await PortableTools.Ensure(cached, Log, tools) != python) throw new IOException("已完成的工具未复用");
        var project = Path.Combine(root, "project");
        Directory.CreateDirectory(project);
        foreach (var directory in new[] { "pcrscript", "images" })
        {
            Directory.CreateDirectory(Path.Combine(project, directory));
            foreach (var file in Directory.GetFiles(Path.Combine(source, directory), "*", SearchOption.AllDirectories))
            {
                if (file.EndsWith(".pyc") || file.Contains("__pycache__")) continue;
                var target = Path.Combine(project, file.Substring(source.TrimEnd(Path.DirectorySeparatorChar).Length + 1));
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.Copy(file, target, true);
            }
        }
        foreach (var name in new[] { "requirements.txt", "runtime_defaults.yml" }) File.Copy(Path.Combine(source, name), Path.Combine(project, name), true);
        var installed = await PythonEnvironment.Install(project, python, Log);
        var catalog = JsonNode.Parse(await Backend.Command(installed, ["-X", "utf8", "pcrscript/desktop.py", "catalog"], project));
        if (catalog?["catalog"]?.AsArray().Count is not > 0) throw new IOException("新环境未能加载任务目录");
        Log("新环境已成功加载任务目录。");
        Log("Portable tools, fresh virtual environment, dependencies and catalog passed. No game was operated.");
    }
}
