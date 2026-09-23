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
        ["Dungeon"] = "地下城首通", ["CharacterUpgrade"] = "角色强化", ["CharacterBond"] = "好感度与角色剧情",
        ["Abyss"] = "深域推进", ["elements"] = "推进属性列表",
        ["max_failures_per_stage"] = "首次探索失败上限", ["max_repeat_failures_per_stage"] = "历史失败关卡补试上限", ["source_urls"] = "优先攻略链接（B站或攻略网页）", ["history_dir"] = "深域尝试历史目录", ["allow_five_star_upgrade"] = "危险操作：允许拟上场角色升至5星", ["allow_divine_amulets"] = "危险操作：允许消耗女神秘石兑换碎片", ["discover_sources"] = "检索对应关卡攻略",
        ["sources"] = "攻略搜索选项", ["task_type"] = "玩法标识", ["stage"] = "目标关卡", ["category_terms"] = "玩法关键词",
        ["browser_session"] = "使用隔离浏览器会话", ["browser_channel"] = "浏览器通道", ["browser_cache_dir"] = "浏览器会话缓存目录",
        ["area"] = "目标区域", ["allow_local_trials"] = "允许按账号培养试打", ["use_local_teams"] = "使用旧本地队伍文件", ["auto_equip"] = "分配现有特别装备",
        ["preflight"] = "开战前核验整条路线", ["max_battles"] = "本次战斗次数上限",
        ["review_on_unexpected"] = "异常时保留现场并停止接续", ["max_batches"] = "最大强化批数",
        ["max_characters"] = "本轮最多检查角色数", ["max_pages"] = "角色列表最大翻页数", ["max_story_steps_per_character"] = "单角色剧情步骤上限", ["max_gifts_per_character"] = "单角色礼物消耗上限",
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
            var fieldsPanel = new StackPanel { Margin = new Thickness(4, 12, 4, 4) };
            OptionsPanel.Children.Add(new Expander { Header = OptionLabels.GetValueOrDefault(section, section),
                IsExpanded = section == "Extra", Content = fieldsPanel });
            if (NeedsStrategyHint(section)) fieldsPanel.Children.Add(CreateStrategyHint());
            if (value is JsonObject fields)
                foreach (var (key, node) in fields) AddOption(section, key, node, fieldsPanel, _optionEditors);
            else AddOption(section, null, value, fieldsPanel, _optionEditors);
        }
        BuildSpecialOptions();
    }

    private void AddOption(string section, string? key, JsonNode? value, StackPanel target, List<(string Section, string? Key, JsonValueKind Kind, FrameworkElement Editor)> editors)
    {
        // Diagnostic-only modes remain in YAML and in the execution options,
        // but are not regular user-facing controls in either options panel.
        if (key is "prepare_only" or "audit_only") return;
        var kind = value?.GetValueKind() ?? JsonValueKind.Null;
        var row = new DockPanel { Margin = new Thickness(0, 0, 0, 6), MaxWidth = 880, HorizontalAlignment = HorizontalAlignment.Stretch };
        var label = new TextBlock { Text = OptionLabels.GetValueOrDefault(key ?? section, key ?? section), Width = target == SpecialOptionsPanel ? 195 : 240, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0,0,12,0), VerticalAlignment = VerticalAlignment.Center };
        row.Children.Add(label);
        FrameworkElement editor;
        if (kind is JsonValueKind.True or JsonValueKind.False)
            editor = new CheckBox { IsChecked = value!.GetValue<bool>(), VerticalAlignment = VerticalAlignment.Center };
        else editor = new TextBox { MinWidth = 120, TextWrapping = TextWrapping.Wrap, Text = kind == JsonValueKind.String ? value!.GetValue<string>() : value?.ToJsonString() ?? "null",
            IsReadOnly = section == "Extra" && key == "dnpath" && _settings.SetupCompleted,
            ToolTip = section == "Extra" && key == "dnpath" ? "目标模拟器在环境设置中修改" : null };
        row.Children.Add(editor); target.Children.Add(row);
        editors.Add((section, key, kind, editor));
        if (editors == _optionEditors)
        {
            if (editor is TextBox text) text.TextChanged += (_, _) => MarkConfigDirty();
            else if (editor is CheckBox check)
            {
                check.Checked += (_, _) => MarkConfigDirty();
                check.Unchecked += (_, _) => MarkConfigDirty();
            }
        }
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
            if (NeedsStrategyHint(section!)) SpecialOptionsPanel.Children.Add(CreateStrategyHint());
            if (value is JsonObject fields)
                foreach (var (key, node) in fields) AddOption(section!, key, node, SpecialOptionsPanel, _specialOptionEditors);
        }
    }

    private static bool NeedsStrategyHint(string section) =>
        section is "Abyss" or "Dungeon" or "StoryEvent" or "RevivalEvent";

    private static TextBlock CreateStrategyHint() => new()
    {
        Text = "自动搜索与解析队伍可能失败；遇到无法配队或进度停滞，可启动 Agent，针对这个任务单独执行并复核报告。",
        TextWrapping = TextWrapping.Wrap,
        Foreground = System.Windows.Media.Brushes.DarkGoldenrod,
        Margin = new Thickness(0, 0, 0, 10),
        MaxWidth = 880
    };

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
                var label = OptionLabels.GetValueOrDefault(key ?? section, key ?? section);
                try { value = kind == JsonValueKind.String ? JsonValue.Create(text) : JsonNode.Parse(text); }
                catch (JsonException) { throw new FormatException($"「{label}」格式无效，请填写{(kind == JsonValueKind.Number ? "数字" : "有效 JSON")}。"); }
                if (kind == JsonValueKind.Number && value?.GetValueKind() != JsonValueKind.Number)
                    throw new FormatException($"「{label}」必须是数字。");
            }
            if (key is null) options[section] = value;
            else options[section]![key] = value;
        }
        return options;
    }
}
