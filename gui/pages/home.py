from functools import partial

from flet import (ClipBehavior, Column, Container, CrossAxisAlignment,
                  DataTable, Divider, IconButton, MainAxisAlignment,
                  OutlinedButton, PopupMenuButton, PopupMenuItem,
                  PopupMenuPosition, ResponsiveRow, Row, Stack, Text,
                  TextAlign, TextThemeStyle, alignment, colors, icons, margin,
                  padding, DataColumn, DataRow, DataCell, AlertDialog)

from gui.source.device_sniff import DeviceSniff
from gui.source.models import Device, SourceType
from gui.storage import KEY_SELECTED_SOURCES, KVStorage, schedule_storage
from gui.source.runtime import device_runtime, RunningState
from .schedule import ScheduleList
from typing import Iterable


class DeviceToolBar(Row):

    def __init__(self, on_refresh=None, on_source_change=None):
        super().__init__()
        self.alignment = MainAxisAlignment.END
        self.on_source_change = on_source_change
        self.on_refresh = on_refresh
        self.setup_views()
    
    def setup_views(self):
        self.controls = [
            IconButton(icon=icons.REFRESH, on_click=self.on_refresh),
            PopupMenuButton(icon=icons.SETTINGS,
                            menu_position=PopupMenuPosition.UNDER,
                            items=self.generate_items()),
        ]
    
    def get_selected_sources(self)->list[SourceType]:
        selected_sources = KVStorage.get(KEY_SELECTED_SOURCES)
        if not selected_sources:
            selected_sources = [SourceType.General]
        return selected_sources
    
    def on_item_click(self, source, e):
        selected_sources = self.get_selected_sources()
        if source in selected_sources:
            selected_sources.remove(source)
        else:
            selected_sources.append(source)
        KVStorage.set(KEY_SELECTED_SOURCES, selected_sources)
        self.setup_views()
        self.update()
        if self.on_source_change:
            self.on_source_change(e)
    
    def generate_items(self):
        items = []
        supported_sources =  SourceType._member_map_
        selected_sources = self.get_selected_sources()
        for key,value in supported_sources.items():
            item = PopupMenuItem(text=key, checked=value in selected_sources)
            item.on_click = partial(self.on_item_click, value)
            items.append(item)
        return items

class DeviceRow(DataRow):


    def _gen_cells(self, device:Device)->Iterable[DataCell]:
        state = device_runtime.get_running_state(device)
        if not state:
            yield DataCell(IconButton(icon=icons.PLAY_DISABLED, icon_color=colors.GREY, disabled=True))
        else:
            if state.state == RunningState.RUNNING:
                yield DataCell(IconButton(icon=icons.PAUSE_OUTLINED, icon_color=colors.RED, on_click=self.on_stop))
            else:
                yield DataCell(IconButton(icon=icons.PLAY_ARROW_SHARP, icon_color=colors.GREEN, on_click=self.on_start))
        if not state:
            yield DataCell(Text("未配置任务"))
        else:
            if state.state == RunningState.PREPARE:
                yield DataCell(Text("准备就绪"))
            elif state.state == RunningState.RUNNING:
                yield DataCell(Text("正在执行"))
            elif state.state == RunningState.ERROR:
                yield DataCell(Text("执行出错", color=colors.RED))
            elif state.state == RunningState.FINISHED:
                yield DataCell(Text("执行完成"))
            elif state.state == RunningState.STOPPED:
                yield DataCell(Text("执行停止"))
        yield DataCell(Text(device.name))
        if not state:
            yield DataCell(Text("设置配置文件"), show_edit_icon=True, on_tap=self.on_edit_config)
        else:
            yield DataCell(Text(f"配置文件:{state.schedule.name}"), show_edit_icon=True, on_tap=self.on_edit_config)
        progress = state.progress if state else 0
        yield DataCell(Text(f"{progress*100}%"))
        if state and state.current_task:
            yield DataCell(Text(f"当前执行任务：{state.current_task.name}"))
        else:
            yield DataCell(Text(f"无"))
    
    def on_edit_config(self, e):
        dialog = AlertDialog()
        def on_select(schedule):
            device_runtime.assign_schedule(self.device, schedule)
            self.page.close(dialog)
            self.refresh()
        dialog.content = Container(content=ScheduleList(on_edit=on_select, can_delete=False, show_add=False), width=350)
        self.page.open(dialog)

    def on_start(self, e):
        state = device_runtime.get_running_state(self.device)
        if not state:
            return
        device_runtime.start_schedule(state.device, state.schedule)
        self.refresh()

    def on_stop(self, e):
        state = device_runtime.get_running_state(self.device)
        if not state:
            return
        device_runtime.stop_schedule(state.device)
        self.refresh()
    
    def refresh(self):
        self.cells = list(self._gen_cells(self.device))
        self.update()

    def __init__(self, device:Device):
        super().__init__(cells=list(self._gen_cells(device)))
        self.device = device

class DeviceList(Row):

    def __init__(self, devices:list[Device]):
        super().__init__()
        self.expand = True
        self.devices = devices
        self.vertical_alignment = CrossAxisAlignment.START
        self.setup_views()
    
    def did_mount(self):
        device_runtime.set_listener(self.on_refresh)
        return super().did_mount()

    def on_refresh(self):
        self.setup_views()
        self.update()
    
    def setup_views(self):
        self.controls = [DataTable(
            expand=True,
            columns=[
                DataColumn(Text("操作")),
                DataColumn(Text("运行状态")),
                DataColumn(Text("设备名称")),
                DataColumn(Text("配置文件")),
                DataColumn(Text("运行进度")),
                DataColumn(Text("说明")),
            ],
            rows=[DeviceRow(device) for device in self.devices]
        )]

class DevicePanel(Container):
    
    def __init__(self):
        super().__init__()
        self.margin = margin.only(top=15)
        self.padding = 8
        self.expand = True
        self.border_radius = 8
        self.bgcolor = colors.AMBER_50
        self.devices:list[Device] = []
        self.init_device_sniff()
        self.update_contents()
    
    def init_device_sniff(self):
        sources = KVStorage.get(KEY_SELECTED_SOURCES)
        self.device_sniff = DeviceSniff(sources)

    def did_mount(self):
        devices = self.device_sniff.find_devices()
        if len(devices) != len(self.devices):
            self.devices = devices
            self.update_contents()
            self.update()
    
    def update_contents(self):
        if self.devices:
            self.content = Column([
                DeviceToolBar(on_refresh=self.on_refresh),
                DeviceList(self.devices),
            ])
        else:
            self.content = Column([
                DeviceToolBar(on_refresh=self.on_refresh),
                Column([
                    Text("未发现设备，请尝试手动刷新"),
                    OutlinedButton(icon=icons.REFRESH_ROUNDED, text="刷新", on_click=self.on_refresh),
                ], expand=True, alignment=MainAxisAlignment.CENTER, horizontal_alignment=CrossAxisAlignment.CENTER),
            ], expand=True, horizontal_alignment=CrossAxisAlignment.CENTER, spacing=0)
        
    
    def on_refresh(self, e):
        self.devices = self.device_sniff.find_devices()
        self.update_contents()
        self.update()
    
    def on_source_change(self, e):
        self.init_device_sniff()

class HomeView(Container):

    def __init__(self):
        super().__init__()
        self.padding = padding.only(top=18, left=16, right=16)
        self.content = Column([
            Text("设备列表",theme_style=TextThemeStyle.HEADLINE_MEDIUM),
            Text("请在下方设备列表中选择合适的设备启动脚本，如果没有设备显示可以选择手动点击刷新按钮或修改检测设备模式后尝试刷新。", theme_style=TextThemeStyle.BODY_MEDIUM),
            DevicePanel(),
        ], horizontal_alignment=CrossAxisAlignment.CENTER)