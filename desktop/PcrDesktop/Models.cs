using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace PcrDesktop;

public sealed class TaskRow
{
    public bool Enabled { get; set; } = true;
    public string Name { get; set; } = "";
    public string Args { get; set; } = "[]";
    public string Label { get; set; } = "";
    public string CategoryLabel { get; set; } = "";
    public string DisplayName => string.IsNullOrEmpty(Label) ? Name : Label;
}

public sealed record TaskChoice(string Name, string Label, JsonArray Parameters, string Description, string Category = "special", string? ConfigSection = null, bool RequiresDevice = true)
{
    public override string ToString() => Label;
}

public sealed record RunChoice(string Path, string Label)
{
    public override string ToString() => Label;
}

public sealed record ConfigChoice(string Path, string Label)
{
    public override string ToString() => Label;
}

public sealed class Settings
{
    public string Workspace { get; set; } = "";
    public string Python { get; set; } = "";
    public string EmulatorDirectory { get; set; } = "";
    public bool SetupCompleted { get; set; }
    public string BootstrapPython { get; set; } = "python";
    public string Config { get; set; } = "daily_config.yml";
    public string Repository { get; set; } = DefaultRepository;
    public string Branch { get; set; } = "master";
    public bool DownloadCoreOnly { get; set; } = true;
    public List<string> RecentConfigs { get; set; } = [];
    public static string FilePath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PcrDesktop", "settings.json");
    internal const string DefaultRepository = "https://github.com/Gibberer/pcr-script.git";
    internal static string ResolveBranch(string repository, string? branch) =>
        (string.IsNullOrWhiteSpace(branch) ||
         repository == DefaultRepository && branch == "codex/agent-driven-story-events") ? "master" : branch!;

    public static Settings Load()
    {
        try
        {
            var settings = JsonSerializer.Deserialize<Settings>(File.ReadAllText(FilePath)) ?? new();
            // Older GUI builds stored the development branch as their default.
            // Migrate that exact value while keeping deliberate custom branches.
            settings.Branch = ResolveBranch(settings.Repository, settings.Branch);
            return settings;
        }
        catch (Exception e) when (e is IOException or JsonException) { return new(); }
    }

    public void Save()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
        var temp = FilePath + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(this));
        if (File.Exists(FilePath)) File.Replace(temp, FilePath, null);
        else File.Move(temp, FilePath);
    }
}
