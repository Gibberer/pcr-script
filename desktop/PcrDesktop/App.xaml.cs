using System.Windows;
using System.IO;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace PcrDesktop;

public partial class App : Application
{
    private Mutex? _instance;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Length >= 4 && e.Args[0] == "--live-check")
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown;
            try
            {
                if (File.Exists(e.Args[1] + ".error.txt")) File.Delete(e.Args[1] + ".error.txt");
                if (Settings.ResolveBranch(Settings.DefaultRepository, "codex/agent-driven-story-events") != "master" ||
                    Settings.ResolveBranch(Settings.DefaultRepository, "feature/custom") != "feature/custom" ||
                    new Settings().Branch != "master")
                    throw new InvalidOperationException("源码下载分支设置不正确");
                var window = new MainWindow(loadSettings: false);
                MainWindow = window;
                await window.LoadSmoke(e.Args[2], e.Args[3]);
                window.SelectSmokeTab(0);
                window.Show();
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                await Task.Delay(250);
                SaveVisibleWindow(window, e.Args[1]);

                var addTask = window.CreateAddTaskPreview();
                addTask.Owner = window;
                addTask.Loaded += (_, _) => Dispatcher.BeginInvoke(() =>
                {
                    SaveVisibleWindow(addTask, e.Args[1] + ".addtask.png");
                    addTask.ConfirmForLiveCheck();
                }, DispatcherPriority.ApplicationIdle);
                if (addTask.ShowDialog() != true || addTask.Result?.Name != "get_gift")
                    throw new InvalidOperationException("实际添加任务窗口未能确认所选项目");

                window.SelectSmokeTab(1);
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                SaveVisibleWindow(window, e.Args[1] + ".special.png");

                var setup = new SetupWindow(new Settings { Workspace = @"C:\PCR\pcr-script", Python = @"C:\Python312\python.exe" });
                setup.Owner = window;
                setup.Show();
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                SaveVisibleWindow(setup, e.Args[1] + ".setup.png");
                setup.Close();
                window.Close();
                Shutdown(0);
            }
            catch (Exception error)
            {
                File.WriteAllText(e.Args[1] + ".error.txt", error.ToString());
                Shutdown(1);
            }
            return;
        }
        if (e.Args.Length >= 2 && e.Args[0] == "--smoke")
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown;
            try
            {
                // Optional local test repository exercises the actual download path.
                if (e.Args.Length >= 6)
                {
                    var coreOnly = e.Args.Length < 7 || e.Args[6] != "full";
                    await RuntimeSource.Download(e.Args[4], e.Args[5], e.Args[2], coreOnly: coreOnly);
                    if (coreOnly)
                    {
                        // Simulate an existing core checkout whose old sparse
                        // rules did not include the relocated root defaults.
                        await Backend.Command("git", ["sparse-checkout", "set", "--no-cone", "--stdin"], e.Args[2],
                            "/pcrscript/\n/images/\n/requirements.txt\n");
                        if (File.Exists(Path.Combine(e.Args[2], "runtime_defaults.yml")))
                            throw new InvalidOperationException("旧版核心下载范围未被模拟");
                        await RuntimeSource.IncludeRootDefaultsForUpdate(e.Args[2]);
                        if (!File.Exists(Path.Combine(e.Args[2], "runtime_defaults.yml")))
                            throw new InvalidOperationException("源码更新未恢复根目录默认选项");
                    }
                }
                var window = new MainWindow(loadSettings: false);
                if (e.Args.Length >= 4) await window.LoadSmoke(e.Args[2], e.Args[3]);
                // Render detached content: an unshown Window is not a renderable
                // presentation source. No foreground window is created for CI.
                var content = (FrameworkElement)window.Content;
                window.Content = null;
                var surface = new System.Windows.Controls.Border
                {
                    Width = 1180, Height = 820, Background = new SolidColorBrush(Color.FromRgb(243, 245, 248)), Child = content
                };
                InheritWindowText(surface, window);
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(e.Args[1]))!);
                for (int tab = 0; tab < (e.Args.Length >= 4 ? 6 : 1); tab++)
                {
                    window.SelectSmokeTab(tab);
                    surface.Measure(new Size(1180, 820));
                    surface.Arrange(new Rect(0, 0, 1180, 820));
                    surface.UpdateLayout();
                    var image = new RenderTargetBitmap(1180, 820, 96, 96, PixelFormats.Pbgra32);
                    image.Render(surface);
                    using var stream = File.Create(e.Args[1] + (tab == 0 ? "" : $".tab{tab}.png"));
                    var encoder = new PngBitmapEncoder();
                    encoder.Frames.Add(BitmapFrame.Create(image));
                    encoder.Save(stream);
                }
                if (e.Args.Length >= 4)
                {
                    var addTask = window.CreateAddTaskPreview();
                    var addContent = (FrameworkElement)addTask.Content;
                    addTask.Content = null;
                    var addSurface = new System.Windows.Controls.Border { Width = 590, Height = 660, Background = Brushes.White, Child = addContent };
                    InheritWindowText(addSurface, addTask);
                    addSurface.Measure(new Size(590, 660)); addSurface.Arrange(new Rect(0, 0, 590, 660)); addSurface.UpdateLayout();
                    var addImage = new RenderTargetBitmap(590, 660, 96, 96, PixelFormats.Pbgra32); addImage.Render(addSurface);
                    using (var addStream = File.Create(e.Args[1] + ".addtask.png"))
                    {
                        var addEncoder = new PngBitmapEncoder(); addEncoder.Frames.Add(BitmapFrame.Create(addImage)); addEncoder.Save(addStream);
                    }
                    surface.Width = 932; surface.Height = 632;
                    for (int tab = 0; tab < 2; tab++)
                    {
                        window.SelectSmokeTab(tab);
                        surface.Measure(new Size(932, 632));
                        surface.Arrange(new Rect(0, 0, 932, 632));
                        surface.UpdateLayout();
                        var smallImage = new RenderTargetBitmap(932, 632, 96, 96, PixelFormats.Pbgra32);
                        smallImage.Render(surface);
                        using var smallStream = File.Create(e.Args[1] + $".small{tab}.png");
                        var smallEncoder = new PngBitmapEncoder();
                        smallEncoder.Frames.Add(BitmapFrame.Create(smallImage)); smallEncoder.Save(smallStream);
                    }
                    var setupSettings = new Settings { Workspace = e.Args[2], Python = e.Args[3] };
                    if (!SetupWindow.IsProject(e.Args[2]) || SetupWindow.IsReady(setupSettings))
                        throw new InvalidOperationException("首次引导的工程/必需设置检查失败");
                    setupSettings.Workspace = @"C:\PCR\pcr-script";
                    setupSettings.Python = @"C:\Python312\python.exe";
                    var setup = new SetupWindow(setupSettings);
                    var setupContent = (FrameworkElement)setup.Content;
                    setup.Content = null;
                    var setupSurface = new System.Windows.Controls.Border { Width = 760, Height = 730, Background = Brushes.White, Child = setupContent };
                    InheritWindowText(setupSurface, setup);
                    setupSurface.Measure(new Size(760, 730));
                    setupSurface.Arrange(new Rect(0, 0, 760, 730));
                    setupSurface.UpdateLayout();
                    var setupImage = new RenderTargetBitmap(760, 730, 96, 96, PixelFormats.Pbgra32);
                    setupImage.Render(setupSurface);
                    using var setupStream = File.Create(e.Args[1] + ".setup.png");
                    var encoder = new PngBitmapEncoder();
                    encoder.Frames.Add(BitmapFrame.Create(setupImage)); encoder.Save(setupStream);
                }
                Shutdown(0);
            }
            catch (Exception error)
            {
                File.WriteAllText(e.Args[1] + ".error.txt", error.ToString());
                Shutdown(1);
            }
            return;
        }
        _instance = new Mutex(true, @"Local\PcrDesktop", out var first);
        if (!first) { MessageBox.Show("PCR 控制台已打开。"); Shutdown(); return; }
        ShutdownMode = ShutdownMode.OnExplicitShutdown;
        var settings = Settings.Load();
        bool ready = SetupWindow.IsReady(settings);
        if (ready)
        {
            try { await PythonEnvironment.RequireReady(settings); }
            catch (Exception error) when (error is IOException or System.ComponentModel.Win32Exception) { ready = false; }
        }
        if (!ready && new SetupWindow(settings).ShowDialog() != true)
        {
            Shutdown(); return;
        }
        var main = new MainWindow();
        MainWindow = main;
        ShutdownMode = ShutdownMode.OnMainWindowClose;
        main.Show();
    }

    private static void InheritWindowText(DependencyObject surface, Window window)
    {
        System.Windows.Documents.TextElement.SetFontFamily(surface, window.FontFamily);
        System.Windows.Documents.TextElement.SetFontSize(surface, window.FontSize);
        System.Windows.Documents.TextElement.SetForeground(surface, window.Foreground);
    }

    private static void SaveVisibleWindow(Window window, string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        window.UpdateLayout();
        var size = window.RenderSize;
        if (size.Width < 100 || size.Height < 100) throw new InvalidOperationException("实际窗口尚未完成布局");
        var bitmap = new RenderTargetBitmap((int)Math.Ceiling(size.Width), (int)Math.Ceiling(size.Height), 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(window);
        using var stream = File.Create(path);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        encoder.Save(stream);
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _instance?.Dispose();
        base.OnExit(e);
    }
}
