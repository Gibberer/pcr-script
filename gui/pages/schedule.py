from typing import Callable

from flet import (BeveledRectangleBorder, Card, CircleBorder, Column,
                  Container, CrossAxisAlignment, Draggable,
                  FloatingActionButton, IconButton, ListTile,
                  MainAxisAlignment, OutlinedButton, RoundedRectangleBorder,
                  Row, ScrollMode, Stack, Text, TextButton, TextField,
                  TextOverflow, TextThemeStyle, VerticalDivider, border,
                  colors, icons, margin, padding, DragTarget, alignment, 
                  DragTargetAcceptEvent,Ref, AlertDialog, animation, transform,
                  Image, Icon, Markdown, TextStyle)

from gui.source.models import Schedule, Task
from gui.source.tasks import taskRepository
from gui.utils import text2color
from gui.storage import schedule_storage


class TaskItem(Card):

    def __init__(self, task:Task, on_click:Callable[[Task],None]=None, color=None):
        super().__init__()
        self.height = 80
        self.task = task
        self.tooltip = task.desc
        if color:
            self.color = color
        else:
            self.color = text2color(task.name)
        self.shape = RoundedRectangleBorder(radius=4)
        self.content =Container(
            content=Column([
                Text(task.name, color=colors.WHITE, max_lines=1),
                Text(task.desc, color=colors.WHITE, max_lines=2, theme_style=TextThemeStyle.LABEL_SMALL, overflow=TextOverflow.ELLIPSIS)
            ]), padding=padding.all(6), on_click=lambda _: on_click and on_click(task), ink=on_click,
        )

class TaskList(Column):
    
    def __init__(self, filter=None, on_add:Callable[[Task], None]=None):
        super().__init__()
        self.scroll = ScrollMode.AUTO
        self.expand = True
        self.spacing = 2
        self.controls = []
        self.horizontal_alignment = CrossAxisAlignment.STRETCH
        self.on_add = on_add
        for task in taskRepository.get_tasks():
            self.controls.append(
                Draggable(
                    group="task",
                    content=TaskItem(task, on_click=self.on_add),
                    content_feedback=Container(content=TaskItem(task), opacity=0.8, width=350)
                )
            )
        

class TaskSearch(Column):
    
    def __init__(self, on_add:Callable[[Task], None]):
        super().__init__()
        self.width = 350
        self.search = TextField(hint_text="搜索任务")
        self.controls = [
            self.search,
            TaskList(on_add=on_add),
        ]

class TaskArrange(Container):
    
    def __init__(self, schedule:Schedule):
        super().__init__()
        self.expand = True
        self.schedule = schedule
        self.tasks = self.schedule.tasks
        self.setup_views()
    
    @property
    def estimate_width(self):
        return self.page.window.width - 350 - 50
    
    def create_task_item(self, task:Task):
        task_item = Ref[Draggable]()
        return Draggable(
            group="arrange",
            content_feedback=Container(
                width=350,
                content=TaskItem(task),
                opacity=0.8
            ),
            content_when_dragging=Container(
                content=TaskItem(task, color=colors.GREY_100),
            ),
            ref=task_item,
            content = DragTarget(
                group="arrange",
                on_accept=self.on_item_accept,
                on_leave=self.on_item_leave,
                on_move=self.on_item_move,
                content=Container(
                    expand=True,
                    animate_offset=animation.Animation(300),
                    content=TaskItem(task),
                    on_long_press=lambda _: self.confirm_remove_task(task, task_item.current)
                ),
            ))
    
    def on_item_move(self, e):
        source = self.page.get_control(e.src_id)
        if source.group != e.control.group:
            return
        if source.content == e.control:
            return
        container = e.control.content
        if e.x < self.estimate_width/2:
            container.offset = transform.Offset(0.3, 0)
        else:
            container.offset = transform.Offset(-0.3, 0)
        container.update()

    def on_item_accept(self, e):
        container = e.control.content
        container.offset = transform.Offset(0, 0)
        container.update()
        src = self.page.get_control(e.src_id)
        target = e.control.parent
        src_index = self.task_items.index(src)
        target_index = self.task_items.index(target)
        if src_index == target_index:
            return
        if e.x < self.estimate_width / 2:
            self.tasks.insert(target_index, self.tasks[src_index])
        else:
            self.tasks.insert(target_index+1, self.tasks[src_index])
        if src_index > target_index:
            src_index +=1
        self.tasks.pop(src_index)
        self.setup_views()
        self.update()

    def on_item_leave(self, e):
        container = e.control.content
        container.offset = transform.Offset(0, 0)
        container.update()

    def setup_views(self):
        self.task_items = [ self.create_task_item(task) for task in self.tasks]
        if self.task_items:
            content = Column(self.task_items, scroll=ScrollMode.HIDDEN, horizontal_alignment=CrossAxisAlignment.STRETCH, spacing=2)
        else:
             content = Container(
                content=Text("this is arrange view"),
                alignment=alignment.center,
            )
        self.content = Container(content=content, expand=True, alignment=alignment.top_left)
    
    def add_task(self, task:Task):
        self.tasks.append(task)
        self.task_items.append(self.create_task_item(task))
        if len(self.task_items) == 1:
            self.setup_views()
        self.update()
        if isinstance(self.content.content, Column):
            self.content.content.scroll_to(offset=-1)
    
    def confirm_remove_task(self, task:Task, task_item):
        dialog = AlertDialog( 
                            title=Text("请确认"), 
                            content=Text(f"删除任务：{task.name}"),
                            actions=[
                                TextButton("取消", on_click=lambda _: self.page.close(dialog)),
                                TextButton("确认", on_click=lambda _: self.page.close(dialog) or self.remove_task(task, task_item)),
                            ] )
        self.page.open(dialog)

    def remove_task(self, task:Task, task_item):
        self.tasks.remove(task)
        self.task_items.remove(task_item)
        self.update()


class ScheduleEdit(Card):

    def __init__(self, schedule:Schedule|None, on_save:Callable[[Schedule|None],None]):
        super().__init__()
        self.margin = margin.only(top=200)
        self.shape = RoundedRectangleBorder(radius=0)
        self.expand = True
        self.elevation = 8
        self.on_save = on_save
        self.schedule = schedule if schedule else Schedule()
        self.task_arrange = TaskArrange(self.schedule)
        self.task_search = TaskSearch(on_add=self.add_task)
        self.left_part = Container(
            content=Stack([
                DragTarget(
                    group="task",
                    content=Column(controls=[
                        TextField(label="计划名称",value=self.schedule.name,width=350, height=40, max_lines=1, 
                                  label_style=TextStyle(size=12), text_size=14, on_change=self.on_title_change),
                        self.task_arrange
                    ]),
                    on_leave=self.on_leave,
                    on_accept=self.on_accept,
                    on_will_accept=self.on_will_accept
                ),
                IconButton(icon=icons.CLOSE, on_click=lambda _: self.on_save(), right=8, top=8, tooltip="Close", bgcolor=colors.WHITE),
                FloatingActionButton(icon=icons.CHECK_SHARP, on_click=lambda _: self.on_save(self.schedule), right=8, bottom=8, 
                                     bgcolor=colors.BLUE_400, tooltip="Save", shape=CircleBorder(), foreground_color=colors.WHITE)
            ], expand=True), expand=True, border=border.all(2, colors.TRANSPARENT),
        )
        self.content = Row([
            self.left_part,
            VerticalDivider(),
            self.task_search,
            Container(width=4),
        ], spacing=0)

    def on_title_change(self, e):
        self.schedule.name = e.control.value
        if not self.schedule.name:
            self.schedule.name = self.schedule.id
    
    def add_task(self, task:Task):
        self.task_arrange.add_task(task)
    
    def on_leave(self, e):
        self.left_part.border = border.all(2, colors.TRANSPARENT)
        self.update()

    def on_accept(self, e):
        self.left_part.border = border.all(2, colors.TRANSPARENT)
        self.update()
        src = e.page.get_control(e.src_id)
        if src.group == 'task':
            assert isinstance(src.content, TaskItem)
            self.task_arrange.add_task(src.content.task)

    def on_will_accept(self, e):
        if e.data == "true":
            self.left_part.border = border.all(2, colors.PINK_400)
            self.update()
        
class ScheduleCard(Card):


    def _schedule_to_markdown(self, schedule:Schedule):
        text = f"### {schedule.name}\n"
        for task in schedule.tasks:
            text += f"* {task.name}\n"
        return text

    def __init__(self, schedule:Schedule, on_edit:Callable[[Schedule|None],None], on_delete:Callable[[Schedule|None],None]):
        super().__init__()
        self.schedule = schedule
        self.on_edit = on_edit
        self.content = Container(content=Markdown(self._schedule_to_markdown(self.schedule)), on_click=lambda _: self.on_edit(self.schedule), 
                                                  ink=True, padding=padding.all(4), width=160, height=200, clip_behavior="antiAlias", on_long_press=lambda _: on_delete(self.schedule))

class ScheduleAdd(Card):

    def __init__(self, on_edit:Callable[[Schedule|None],None]):
        super().__init__()
        self.content = Container(content=Icon(name=icons.ADD, size=36), on_click=lambda _: on_edit(), ink=True, padding=padding.all(4), width=160, height=200, clip_behavior="antiAlias")

class ScheduleList(Row):

    def __init__(self, on_edit:Callable[[Schedule|None],None], can_delete=True, show_add=True):
        super().__init__()
        self.wrap = True
        self.expand = True
        self.can_delete = can_delete
        self.show_add = show_add
        self.alignment = MainAxisAlignment.START
        self.vertical_alignment = CrossAxisAlignment.START
        self.on_edit = on_edit
        self.setup_views()
    
    def setup_views(self):
        self.controls = [ScheduleCard(schedule, self.on_edit, self.on_delete) for schedule in schedule_storage.get_schedule_list()]
        if self.show_add:
            self.controls.append(
                ScheduleAdd(self.on_edit)
            )
    
    def on_delete(self, schedule:Schedule):
        if not self.can_delete:
            return
        dialog = AlertDialog( 
                            title=Text("请确认"), 
                            content=Text(f"删除计划：{schedule.name}"),
                            actions=[
                                TextButton("取消", on_click=lambda _: self.page.close(dialog)),
                                TextButton("确认", on_click=lambda _: self.page.close(dialog) or schedule_storage.remove_schedule(schedule) or self.setup_views() or self.update()),
                            ] )
        self.page.open(dialog)

class ScheduleView(Container):
    
    def __init__(self):
        super().__init__()
        self.expand = True
        self.schedule_list = ScheduleList(self.on_edit)
        self.schedule_edit = ScheduleEdit(None, self.on_save)
        self.in_edit = False
        self.setup_views()
    
    def on_edit(self, schedule:Schedule=None):
        self.in_edit = True
        if schedule:
            schedule = schedule.model_copy()
        self.schedule_edit = ScheduleEdit(schedule, self.on_save)
        self.setup_views()
        self.update()

    def on_save(self, schedule:Schedule=None):
        self.in_edit = False
        if schedule and schedule.tasks:
            schedule_storage.save_schedule(schedule)
        self.schedule_list.setup_views()
        self.setup_views()
        self.update()
    
    def setup_views(self):
        if self.in_edit:
            self.content = Stack(
                [
                    self.schedule_list,
                    self.schedule_edit,
                ],
            )
        else:
            self.content = Column([self.schedule_list], expand=True)