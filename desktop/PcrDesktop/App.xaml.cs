using System.Windows;
using System.IO;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace PcrDesktop;

public partial class App : Application
{
    private Mutex? _instance;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Length >= 2 && e.Args[0] == "--smoke")
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown;
            try
            {
                // Optional local test repository exercises the actual download path.
                if (e.Args.Length >= 6)
                    await RuntimeSource.Download(e.Args[4], e.Args[5], e.Args[2], coreOnly: e.Args.Length < 7 || e.Args[6] != "full");
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
                    var setupSettings = new Settings { Workspace = e.Args[2], Python = e.Args[3] };
                    if (!SetupWindow.IsProject(e.Args[2]) || SetupWindow.IsReady(setupSettings))
                        throw new InvalidOperationException("首次引导的工程/必需设置检查失败");
                    setupSettings.Workspace = Path.Combine(e.Args[2], "cache", "desktop", "new-project");
                    var setup = new SetupWindow(setupSettings);
                    var setupContent = (FrameworkElement)setup.Content;
                    setup.Content = null;
                    var setupSurface = new System.Windows.Controls.Border { Width = 760, Height = 730, Background = Brushes.White, Child = setupContent };
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

    protected override void OnExit(ExitEventArgs e)
    {
        _instance?.Dispose();
        base.OnExit(e);
    }
}
