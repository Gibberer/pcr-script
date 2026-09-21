using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace PcrDesktop;

internal static class StatusDisplay
{
    internal static readonly JsonSerializerOptions ReadableJson = new()
    { WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    internal static string FormatStep(JsonNode? value)
    {
        if (value is not JsonArray step || step.Count != 2) return Format(value);
        var kind = step[0]?.ToString() switch { "action" => "操作", "task" => "任务", "wait" => "等待", var other => other };
        var detail = step[1];
        // Older logs contain a JSON string inside the current_step array.
        if (detail is JsonValue text && text.TryGetValue<string>(out var raw))
        {
            try { detail = JsonNode.Parse(raw); }
            catch (JsonException) { }
        }
        return kind + "：" + Format(detail);
    }

    internal static string Format(JsonNode? value) => value is JsonValue ? value.ToString() : value?.ToJsonString(ReadableJson) ?? "—";
}
