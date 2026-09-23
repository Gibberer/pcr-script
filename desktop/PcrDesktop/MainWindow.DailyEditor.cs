using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;

namespace PcrDesktop;

public partial class MainWindow
{
    private TaskRow? _editingRow;
    private bool _selectingPlan;
    private bool _configDirty;

    private void Layout_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (DailyHero is null || CompactDailyButton is null || SpecialHero is null) return;
        bool compact = e.NewSize.Height < 680;
        DailyHero.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        CompactDailyButton.Visibility = compact ? Visibility.Visible : Visibility.Collapsed;
        SpecialHero.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
    }

    private void MarkConfigDirty()
    {
        _configDirty = true;
        RefreshConfigLabel();
    }

    private void MarkConfigSaved()
    {
        _configDirty = false;
        RefreshConfigLabel();
    }

    private void RefreshConfigLabel()
    {
        CurrentConfigText.Text = (_newConfig ? "未命名配置" : "当前配置：" + ConfigBox.Text)
            + (_configDirty ? "  · 有未保存修改" : _newConfig ? "  · 添加任务后保存" : "  · 已保存");
    }

    private void ResetDailyEditor()
    {
        _editingRow = null;
        TaskPicker.SelectedItem = null;
        ParameterPanel.Children.Clear(); _parameters.Clear();
        EditorTitle.Text = "选择一项日常任务";
        TaskDescription.Text = "从左侧列表选择任务查看和修改参数，或点击「＋ 添加任务」创建新项目。";
        ParameterErrorText.Text = "";
        UpdateEditorButtons();
    }

    private void UpdateEditorButtons()
    {
        var index = PlanGrid.SelectedIndex;
        MoveUpButton.IsEnabled = index > 0;
        MoveDownButton.IsEnabled = index >= 0 && index < _plan.Count - 1;
        RemoveTaskButton.IsEnabled = index >= 0;
        RunSelectedButton.IsEnabled = _editingRow is not null && TaskPicker.SelectedItem is TaskChoice && ParameterErrorText.Text.Length == 0;
    }

    private void ApplyEditor()
    {
        if (_editingRow is null || TaskPicker.SelectedItem is not TaskChoice task) return;
        if (task.Name != _editingRow.Name) throw new InvalidOperationException("任务类型不可在参数编辑中替换，请添加新任务。");
        var args = ParameterValues().ToJsonString();
        if (args != _editingRow.Args)
        {
            _editingRow.Args = args;
            MarkConfigDirty();
            PlanGrid.Items.Refresh();
        }
        ParameterErrorText.Text = "";
    }

    private void DailyParameterChanged()
    {
        if (_selectingPlan || _editingRow is null) return;
        MarkConfigDirty();
        try { ApplyEditor(); }
        catch (FormatException error) { ParameterErrorText.Text = error.Message; }
        UpdateEditorButtons();
    }

    private void Plan_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_selectingPlan) return;
        var selected = PlanGrid.SelectedItem as TaskRow;
        try { ApplyEditor(); }
        catch (FormatException error)
        {
            ParameterErrorText.Text = error.Message;
            _selectingPlan = true; PlanGrid.SelectedItem = _editingRow; _selectingPlan = false;
            Message("请先修正当前任务参数，再选择其他项目。");
            return;
        }
        _selectingPlan = true;
        try
        {
            ResetDailyEditor();
            if (selected is null) return;
            _editingRow = selected;
            TaskPicker.SelectedItem = TaskPicker.Items.Cast<TaskChoice>().FirstOrDefault(t => t.Name == selected.Name);
            EditorTitle.Text = $"第 {_plan.IndexOf(selected)+1} 项 · {selected.DisplayName}";
            BuildParameters(JsonNode.Parse(selected.Args)!.AsArray());
        }
        finally { _selectingPlan = false; UpdateEditorButtons(); }
    }

    private void AddTask(TaskRow row)
    {
        ApplyEditor();
        _plan.Add(row);
        PlanGrid.SelectedItem = row;
        PlanGrid.ScrollIntoView(row);
        MarkConfigDirty();
        Message("已添加到列表末尾，可用上移/下移调整顺序。保存配置后生效。");
    }

    private async void Add_Click(object sender, RoutedEventArgs e) => await Guard(() =>
    {
        ApplyEditor();
        var dialog = new AddTaskWindow(_choices) { Owner = this };
        if (dialog.ShowDialog() == true && dialog.Result is TaskRow row) AddTask(row);
        return Task.CompletedTask;
    });

    private void PlanEnabled_Click(object sender, RoutedEventArgs e)
    {
        MarkConfigDirty();
        UpdateEditorButtons();
    }

    private void MoveSelected(int delta)
    {
        var index = PlanGrid.SelectedIndex;
        if (index < 0 || index+delta < 0 || index+delta >= _plan.Count) return;
        _plan.Move(index, index+delta);
        EditorTitle.Text = $"第 {PlanGrid.SelectedIndex+1} 项 · {_editingRow?.DisplayName}";
        MarkConfigDirty(); UpdateEditorButtons();
    }
    private void Up_Click(object sender, RoutedEventArgs e) => MoveSelected(-1);
    private void Down_Click(object sender, RoutedEventArgs e) => MoveSelected(1);
    private void Remove_Click(object sender, RoutedEventArgs e)
    {
        if (PlanGrid.SelectedItem is not TaskRow row) return;
        var index = PlanGrid.SelectedIndex;
        ResetDailyEditor(); // Removing an item also discards that item's invalid draft.
        _plan.Remove(row);
        PlanGrid.SelectedIndex = Math.Min(index, _plan.Count-1);
        MarkConfigDirty(); UpdateEditorButtons();
    }

    private async Task<bool> MayReplaceConfig()
    {
        if (!_configDirty) return true;
        var decision = MessageBox.Show(this, "当前配置有未保存的修改，是否先保存？", "切换配置",
            MessageBoxButton.YesNoCancel, MessageBoxImage.Question, MessageBoxResult.Cancel);
        if (decision == MessageBoxResult.Cancel) return false;
        if (decision == MessageBoxResult.No) return true;
        await SaveConfig();
        return !_configDirty;
    }

    internal AddTaskWindow CreateAddTaskPreview()
    {
        var dialog = new AddTaskWindow(_choices);
        dialog.Picker.SelectedItem = dialog.Picker.Items.Cast<TaskChoice>().FirstOrDefault(t => t.Name == "get_gift");
        return dialog;
    }

    private void VerifyDailyEditor()
    {
        var add = CreateAddTaskPreview();
        add.Picker.SelectedItem = add.Picker.Items.Cast<TaskChoice>().Single(t => t.Name == "campaign_clean");
        var campaign = add.ReadTask();
        if (campaign.Name != "campaign_clean" || JsonNode.Parse(campaign.Args)!.AsArray().Count != 2 || add.Result is not null)
            throw new InvalidOperationException("添加窗口隔离或参数读取失败");
        AddTask(campaign);
        var firstFlag = (CheckBox)_parameters[0].Editor;
        firstFlag.IsChecked = !firstFlag.IsChecked;
        var edited = campaign.Args;
        if (!_configDirty || JsonNode.Parse(edited)![0]!.GetValue<bool>() != firstFlag.IsChecked)
            throw new InvalidOperationException("参数没有应用到选中行");
        AddTask(new TaskRow { Name = "quick_clean", Args = "[1]" });
        var quick = _editingRow!;
        ((TextBox)_parameters[0].Editor).Text = "invalid";
        PlanGrid.SelectedItem = campaign;
        if (_editingRow != quick || PlanGrid.SelectedItem != quick || ParameterErrorText.Text.Length == 0)
            throw new InvalidOperationException("无效参数被切换行时静默丢弃");
        ((TextBox)_parameters[0].Editor).Text = "2";
        PlanGrid.SelectedItem = campaign;
        if (campaign.Args != edited || quick.Args != "[2]" || campaign.Name != "campaign_clean")
            throw new InvalidOperationException("选中行编辑影响了其他任务");
        MoveSelected(1);
        if (_plan[1] != campaign) throw new InvalidOperationException("排序未保留选中任务");
        Remove_Click(this, new RoutedEventArgs());
        if (_plan.Count != 1 || _plan[0] != quick) throw new InvalidOperationException("移除对象不符");
        ResetDailyEditor(); _plan.Clear(); MarkConfigSaved();
    }
}
