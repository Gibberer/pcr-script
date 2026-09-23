using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;

namespace PcrDesktop;

public partial class AddTaskWindow : Window
{
    private readonly List<(JsonObject Descriptor, FrameworkElement Editor)> _parameters = [];
    public TaskRow? Result { get; private set; }

    public AddTaskWindow(IEnumerable<TaskChoice> choices)
    {
        InitializeComponent();
        Picker.ItemsSource = choices.Where(t => t.Category == "daily").ToList();
        Picker.SelectedIndex = 0;
    }

    private void SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (Picker.SelectedItem is not TaskChoice task) return;
        Description.Text = task.Description;
        TaskParameters.Fill(task, Parameters, _parameters);
        ErrorText.Text = "";
    }

    internal TaskRow ReadTask()
    {
        if (Picker.SelectedItem is not TaskChoice task) throw new InvalidOperationException("请选择任务");
        return new TaskRow { Name = task.Name, Args = TaskParameters.Read(_parameters).ToJsonString() };
    }

    internal void ConfirmForLiveCheck() => AddButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

    private void Add_Click(object sender, RoutedEventArgs e)
    {
        try { Result = ReadTask(); DialogResult = true; }
        catch (Exception error) when (error is FormatException or InvalidOperationException) { ErrorText.Text = error.Message; }
    }
}
