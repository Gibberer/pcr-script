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
        ["Extra"] = "运行环境", ["StoryEvent"] = "剧情活动", ["RevivalEvent"] = "复刻活动",
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
                foreach (var (key, node) in fields) AddOption(section, key, node);
            else AddOption(section, null, value);
        }
    }

    private void AddOption(string section, string? key, JsonNode? value)
    {
        var kind = value?.GetValueKind() ?? JsonValueKind.Null;
        var row = new DockPanel { Margin = new Thickness(0, 0, 0, 6), MaxWidth = 880, HorizontalAlignment = HorizontalAlignment.Left };
        var label = new TextBlock { Text = OptionLabels.GetValueOrDefault(key ?? section, key ?? section), Width = 275, VerticalAlignment = VerticalAlignment.Center };
        row.Children.Add(label);
        FrameworkElement editor;
        if (kind is JsonValueKind.True or JsonValueKind.False)
            editor = new CheckBox { IsChecked = value!.GetValue<bool>(), VerticalAlignment = VerticalAlignment.Center, Width = 460 };
        else editor = new TextBox { Width = 460, Text = kind == JsonValueKind.String ? value!.GetValue<string>() : value?.ToJsonString() ?? "null",
            IsReadOnly = section == "Extra" && key == "dnpath" && _settings.SetupCompleted,
            ToolTip = section == "Extra" && key == "dnpath" ? "目标模拟器在环境设置中修改" : null };
        row.Children.Add(editor); OptionsPanel.Children.Add(row);
        _optionEditors.Add((section, key, kind, editor));
    }

    private JsonObject ReadOptions()
    {
        var options = (JsonObject)_optionTemplate.DeepClone();
        foreach (var (section, key, kind, editor) in _optionEditors)
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
