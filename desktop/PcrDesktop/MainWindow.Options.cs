using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;

namespace PcrDesktop;

public partial class MainWindow
{
    private JsonObject _optionTemplate = new();
    private readonly List<(string Section, string? Key, JsonValueKind Kind, FrameworkElement Editor)> _optionEditors = [];
    private static readonly Dictionary<string, string> OptionLabels = new()
    {
        ["Dungeon"] = "地下城首通", ["DungeonSources"] = "队伍来源搜索", ["CharacterUpgrade"] = "角色强化",
        ["area"] = "目标地下城", ["allow_local_trials"] = "允许按账号培养试打", ["auto_equip"] = "分配现有特别装备",
        ["preflight"] = "开战前核验整条路线", ["audit_only"] = "只核验，不开战", ["max_battles"] = "本次战斗次数上限",
        ["review_on_unexpected"] = "异常时保留现场并停止接续", ["max_batches"] = "最大强化批数",
        ["aliases"] = "搜索别名", ["region"] = "目标服区", ["max_videos"] = "候选视频数量", ["max_age_hours"] = "缓存有效小时数",
        ["request_timeout"] = "网络请求超时（秒）", ["cache_dir"] = "来源缓存目录", ["Extra"] = "运行环境", ["StoryEvent"] = "剧情活动", ["RevivalEvent"] = "复刻活动",
        ["Gift"] = "礼物领取", ["Caravan"] = "驾车游", ["dnpath"] = "雷电安装目录",
        ["teams"] = "队伍方案文件", ["first_clear"] = "推进首次通关（待实机验证）", ["bosses"] = "挑战首领",
        ["stories"] = "处理剧情", ["memoirs"] = "处理追忆", ["missions"] = "领取任务奖励", ["exchange"] = "兑换奖励",
        ["max_boss_attempts"] = "首领最大尝试次数", ["battle_timeout"] = "战斗超时（秒）", ["timeout"] = "任务超时（秒）",
        ["account_key"] = "账号记录标识", ["auto_dismantle"] = "满仓时按既有规则自动分解", ["free_slots"] = "释放装备空间（500～1000）",
        ["max_gift_batches"] = "最大领取批数", ["max_rolls"] = "最大掷骰批数"
    };

    private void BuildOptions(JsonObject options)
    {
        _optionTemplate = (JsonObject)options.DeepClone();
        if (!string.IsNullOrWhiteSpace(_settings.EmulatorDirectory))
        {
            _optionTemplate["Extra"] ??= new JsonObject();
            _optionTemplate["Extra"]!["dnpath"] = _settings.EmulatorDirectory;
        }
        _optionEditors.Clear(); OptionsPanel.Children.Clear();
        foreach (var (section, value) in _optionTemplate)
        {
            OptionsPanel.Children.Add(new TextBlock { Text = OptionLabels.GetValueOrDefault(section, section), FontSize = 18, FontWeight = FontWeights.SemiBold, Margin = new Thickness(0, 14, 0, 10) });
            if (value is JsonObject fields)
                foreach (var (key, node) in fields) AddOption(section, key, node, OptionsPanel, _optionEditors);
            else AddOption(section, null, value, OptionsPanel, _optionEditors);
        }
        BuildSpecialOptions();
    }

    private void AddOption(string section, string? key, JsonNode? value, StackPanel target, List<(string Section, string? Key, JsonValueKind Kind, FrameworkElement Editor)> editors)
    {
        var kind = value?.GetValueKind() ?? JsonValueKind.Null;
        var row = new DockPanel { Margin = new Thickness(0, 0, 0, 6), MaxWidth = 880, HorizontalAlignment = HorizontalAlignment.Left };
        var label = new TextBlock { Text = OptionLabels.GetValueOrDefault(key ?? section, key ?? section), Width = target == SpecialOptionsPanel ? 215 : 275, VerticalAlignment = VerticalAlignment.Center };
        row.Children.Add(label);
        FrameworkElement editor;
        if (kind is JsonValueKind.True or JsonValueKind.False)
            editor = new CheckBox { IsChecked = value!.GetValue<bool>(), VerticalAlignment = VerticalAlignment.Center, Width = target == SpecialOptionsPanel ? 280 : 460 };
        else editor = new TextBox { Width = target == SpecialOptionsPanel ? 280 : 460, Text = kind == JsonValueKind.String ? value!.GetValue<string>() : value?.ToJsonString() ?? "null",
            IsReadOnly = section == "Extra" && key == "dnpath" && _settings.SetupCompleted,
            ToolTip = section == "Extra" && key == "dnpath" ? "目标模拟器在环境设置中修改" : null };
        row.Children.Add(editor); target.Children.Add(row);
        editors.Add((section, key, kind, editor));
    }

    private JsonObject _specialTemplate = new();
    private JsonObject _defaultOptions = new();
    private readonly List<(string Section, string? Key, JsonValueKind Kind, FrameworkElement Editor)> _specialOptionEditors = [];
    private void BuildSpecialOptions()
    {
        if (SpecialOptionsPanel is null) return;
        SpecialOptionsPanel.Children.Clear(); _specialOptionEditors.Clear();
        _specialTemplate = new JsonObject();
        if (CatalogList.SelectedItem is not TaskChoice task) return;
        foreach (var section in new[] { "Extra", task.ConfigSection }.Where(s => !string.IsNullOrEmpty(s)).Distinct())
        {
            var value = _optionTemplate[section!] ?? _defaultOptions[section!];
            if (value is null) continue;
            _specialTemplate[section!] = value.DeepClone();
            if (section == "Extra") continue; // Emulator is managed in environment settings.
            if (value is JsonObject fields)
                foreach (var (key, node) in fields) AddOption(section!, key, node, SpecialOptionsPanel, _specialOptionEditors);
        }
    }

    private JsonObject ReadOptions() => ReadOptionValues(_optionTemplate, _optionEditors);
    private JsonObject ReadSpecialOptions() => ReadOptionValues(_specialTemplate, _specialOptionEditors);

    private JsonObject ReadOptionValues(JsonObject template, List<(string Section, string? Key, JsonValueKind Kind, FrameworkElement Editor)> editors)
    {
        var options = (JsonObject)template.DeepClone();
        foreach (var (section, key, kind, editor) in editors)
        {
            JsonNode? value;
            if (editor is CheckBox check) value = JsonValue.Create(check.IsChecked == true);
            else
            {
                var text = ((TextBox)editor).Text;
                value = kind == JsonValueKind.String ? JsonValue.Create(text) : JsonNode.Parse(text);
                if (kind == JsonValueKind.Number && value?.GetValueKind() != JsonValueKind.Number)
                    throw new InvalidOperationException($"{section}.{key} 必须是数字");
            }
            if (key is null) options[section] = value;
            else options[section]![key] = value;
        }
        return options;
    }
}
