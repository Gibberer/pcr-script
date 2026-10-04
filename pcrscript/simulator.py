from typing import List
import os
import re
import ast
import subprocess
import win32api
import win32gui
import win32con
from .driver import ADBDriver, Driver, DNDriver, MuMuDriver


class GeneralSimulator():
    '''
    通用模拟器
    '''

    def __init__(self, adb_path="adb"):
        self.adb_path = adb_path

    def get_devices(self) -> List[str]:
        return [serial for serial, state in self.get_device_states().items() if state == 'device']

    def get_device_states(self) -> dict[str, str]:
        """Read connection states without capturing or sending input to any device."""
        try:
            result = subprocess.run([self.adb_path, "devices"], capture_output=True,
                                    text=True, check=True, timeout=15)
        except FileNotFoundError as error:
            raise RuntimeError("未找到 ADB 程序；请在环境设置中选择 adb.exe 或将其加入 PATH") from error
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise RuntimeError("ADB 设备列表读取失败；请检查 adb.exe 和设备连接") from error
        devices = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ('device', 'unauthorized', 'offline', 'recovery', 'sideload', 'bootloader', 'no'):
                devices[parts[0]] = parts[1]
        return devices

    def get_dirvers(self) -> List[Driver]:
        devices = self.get_devices()
        if devices:
            return [ADBDriver(device, self.adb_path) for device in devices]


class DNSimulator(GeneralSimulator):
    '''
    雷电模拟器使用win32api
    '''

    def __init__(self, path, fastclick=False, useADB=True):
        super().__init__()
        self.path = path
        self.fastclick = fastclick
        self.useADB = useADB
        self.last_discovery = None
        if not useADB:
            self.fastclick = True

    def _get_process_descriptions():
        command = "Get-CimInstance -ClassName Win32_Process | Select-Object -Property Description"
        try:
            result = subprocess.run(
                ["powershell.exe", "-Command", command],
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8',
                timeout=15
            )

            raw_output = result.stdout
            lines = raw_output.strip().splitlines()
        
            # 移除前两行的标题 ("Description") 和分隔线 ("-----------")
            # 并过滤掉可能存在的空字符串
            descriptions = [line.strip() for line in lines[2:] if line.strip()]
        
            return descriptions

        except FileNotFoundError:
            print("错误: 'powershell.exe' 未找到。请确保 PowerShell 已安装并在系统 PATH 中。")
            return None
        except subprocess.CalledProcessError as e:
            print(f"执行 PowerShell 命令时出错:")
            print(f"返回码: {e.returncode}")
            print(f"输出: {e.stdout}")
            print(f"错误信息: {e.stderr}")
            return None
        
    def start(self):
        processes = DNSimulator._get_process_descriptions()
        if processes is None:
            raise RuntimeError('无法读取雷电模拟器进程列表，请检查 PowerShell 是否可用')
        if "dnplayer.exe" not in processes:
            subprocess.Popen([os.path.join(self.path, 'dnplayer.exe')])
    
    def open_app(self, packagename, device = None):
        if self.path:
            if device is None:
                device = 0
            command = [os.path.join(self.path, 'ldconsole.exe'), 'runapp',
                       '--index', str(device), '--packagename', packagename]
        else:
            if device is None:
                device = self.get_devices()[0]
            command = [self.adb_path, '-s', str(device), 'shell', 'monkey', '-p', packagename, '1']
        return subprocess.run(command, timeout=30).returncode

    def online(self)->bool:
        if self.path:
            command_result = subprocess.check_output(
                [os.path.join(self.path, 'ldconsole.exe'), 'list2'],
                encoding='mbcs', errors='replace', timeout=15)
            if command_result:
                infos = list(map(lambda x: x.split(","), command_result.split("\n")))
                if infos and int(infos[0][2]) > 0 and int(infos[0][4]) == 1:
                    return True
            return False
        return super().get_devices()

    def get_devices(self) -> List[str]:
        if self.useADB:
            return super().get_devices()
        report = self.discover_windows()
        if report['status'] == 'query_failed':
            return None  # Window discovery must never silently switch to ADB.
        return [str(row['index']) for row in report['devices'] if row['visible']]

    def discover_windows(self):
        """Read-only evidence from this execution context, without window titles."""
        report = dict(driver='leidian', console=os.path.join(self.path, 'ldconsole.exe'),
                      status='not_visible', devices=[], malformed_rows=0)
        try:
            output = subprocess.check_output([report['console'], 'list2'],
                encoding='mbcs', errors='replace', timeout=15)
        except (OSError, subprocess.SubprocessError) as error:
            report.update(status='query_failed', error=type(error).__name__)
            if isinstance(error, subprocess.CalledProcessError):
                report['exit_code'] = f'0x{error.returncode & 0xffffffff:08X}'
            elif isinstance(error, subprocess.TimeoutExpired):
                report['timeout_seconds'] = error.timeout
        else:
            for line in output.splitlines():
                if not line.strip():
                    continue
                fields = line.split(',')
                try:
                    index, window, bound, running = (int(fields[i]) for i in (0, 2, 3, 4))
                    width, height = (int(fields[i]) for i in (7, 8))
                except (ValueError, IndexError):
                    report['malformed_rows'] += 1
                    continue
                report['devices'].append(dict(index=index, window_handle=window,
                    bound_handle=bound, android_started=running == 1,
                    width=width, height=height, visible=window > 0 and bound > 0 and running == 1))
            if any(row['visible'] for row in report['devices']):
                report['status'] = 'visible'
        self.last_discovery = report
        return report

    def discovery_error(self):
        report = self.last_discovery or {}
        if report.get('status') == 'query_failed':
            detail = 'list2 查询失败：'+report.get('error', 'unknown')
            if report.get('exit_code'):
                detail += ' '+report['exit_code']
        else:
            detail = ('list2 返回 '+str(len(report.get('devices', [])))+' 个实例，当前环境无可用窗口'
                      +'，无效记录 '+str(report.get('malformed_rows', 0)))
        return (detail+'。这不能证明模拟器未启动；请核对 Extra.dnpath、Windows 会话和沙箱/权限隔离。'
                'Agent 先运行 scripts/agent/game.py --diagnose；按 docs/run-diagnostics.md '
                '在获准的正常会话重试同一只读截图，勿自动重启或改用其他设备。')

    def get_dirvers(self) -> List[Driver]:
        devices = self.get_devices()
        if devices:
            return [DNDriver(device, self.path, i if self.useADB else int(device), click_by_mouse=self.fastclick)
                    for i, device in enumerate(devices)]
        
    
    def move_to_screen(self, index):
        """
        将窗口移动到指定索引的屏幕居中位置。
        :param index: 屏幕索引 (0 为主屏，1、2... 为副屏)
        """
        hwnd = win32gui.FindWindow(None, "雷电模拟器")
        if not hwnd:
            return

        monitors = win32api.EnumDisplayMonitors()
        if index < 0 or index >= len(monitors):
            return

        hMonitor = monitors[index][0]
        m_left, m_top, m_right, m_bottom = win32api.GetMonitorInfo(hMonitor)["Work"]
        m_width = m_right - m_left
        m_height = m_bottom - m_top

        win_rect = win32gui.GetWindowRect(hwnd)
        w_width = win_rect[2] - win_rect[0]
        w_height = win_rect[3] - win_rect[1]

        center_x = m_left + (m_width - w_width) // 2
        center_y = m_top + (m_height - w_height) // 2

        win32gui.SetWindowPos(
            hwnd, 
            win32con.HWND_TOP, 
            center_x, center_y, 
            0, 0, 
            win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
        )

class MuMuSimulator(GeneralSimulator):
    '''
    MuMu模拟器
    '''

    def __init__(self, path, port='16384', fastclick=False):
        super().__init__()
        self.path = path
        self.port = port
        self.fastclick = fastclick
    
    def _api(self, command):
        return os.popen(f'cmd /C ""{self.path}\shell\MuMuManager.exe" api {command}"').read()
    
    def _get_player_list(self):
        output = self._api('get_player_list')
        result = re.search(r'\[.*?\]', output)
        if result:
            return ast.literal_eval(result.group())
    
    def _check_player_started(self, index):
        output = self._api(f'-v {index} player_state')
        return output and 'start_finished' in output
    
    def _get_devices(self)->tuple[int, List[str]]:
        try:
            player_list:list = self._get_player_list()
            if player_list:
                for i in range(len(player_list)-1, -1, -1):
                    player = player_list[i]
                    if not self._check_player_started(player):
                        player_list.pop(i)
                return 1, player_list
            return 1, []
        except Exception as e:
            print(e)
            os.system(f"adb connect 127.0.0.1:{self.port}")
            return 0, super().get_devices()
    
    def get_devices(self) -> List[str]:
        return self._get_devices()

    def get_dirvers(self) -> List[Driver]:
        state, devices = self._get_devices()
        if state:
            return [MuMuDriver(f"MuMu-{device}", self.path, device, self.fastclick) for device in devices]
        else:
            return [ADBDriver(device) for device in devices]
