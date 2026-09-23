using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;

namespace PcrDesktop;

internal static class TaskParameters
{
    internal static void Fill(TaskChoice task, StackPanel panel,
        List<(JsonObject Descriptor, FrameworkElement Editor)> editors, JsonArray? values = null)
    {
        panel.Children.Clear(); editors.Clear();
        int index = 0;
        foreach (var node in task.Parameters)
        {
            var descriptor = node!.AsObject();
            var value = values is not null && index < values.Count ? values[index] : descriptor["default"];
            panel.Children.Add(new TextBlock { Text = (descriptor["label"] ?? descriptor["name"])!.ToString() +
                (descriptor["required"]!.GetValue<bool>() ? " *" : ""), Margin = new Thickness(0, 8, 0, 0) });
            FrameworkElement editor = descriptor["type"]!.ToString() == "boolean"
                ? new CheckBox { IsChecked = value?.GetValue<bool>() ?? false, Margin = new Thickness(0, 8, 0, 14) }
                : new TextBox { Text = descriptor["type"]!.ToString() == "string" ? value?.GetValue<string>() ?? "" : value?.ToJsonString() ?? "null" };
            panel.Children.Add(editor); editors.Add((descriptor, editor)); index++;
        }
        if (editors.Count == 0) panel.Children.Add(new TextBlock { Text = "此任务没有单独参数。", Foreground = System.Windows.Media.Brushes.SlateGray });
    }

    internal static JsonArray Read(List<(JsonObject Descriptor, FrameworkElement Editor)> editors)
    {
        var result = new JsonArray();
        foreach (var (descriptor, editor) in editors)
        {
            var label = (descriptor["label"] ?? descriptor["name"])!.ToString();
            var kind = descriptor["type"]!.ToString();
            try
            {
                JsonNode? value;
                if (editor is CheckBox check) value = JsonValue.Create(check.IsChecked == true);
                else
                {
                    var text = ((TextBox)editor).Text;
                    value = kind == "string" ? JsonValue.Create(text) : JsonNode.Parse(text);
                    if (kind == "number" && value?.GetValueKind() != JsonValueKind.Number)
                        throw new FormatException("请输入数字");
                }
                if (descriptor["required"]!.GetValue<bool>() && (value is null || kind == "string" && string.IsNullOrWhiteSpace(value.ToString())))
                    throw new FormatException("此项必填");
                result.Add(value);
            }
            catch (Exception error) when (error is JsonException or FormatException)
            {
                throw new FormatException(label + "：" + (error is JsonException ? "请输入有效 JSON" : error.Message));
            }
        }
        return result;
    }
}
