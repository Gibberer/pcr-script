from .models import Device,Schedule,Task
from dataclasses import dataclass
from enum import IntEnum
from threading import Thread
from pcrscript.robot import Robot
from .tasks import taskRepository
from pcrscript.tasks import BaseTask
import time

class RunningState(IntEnum):
    PREPARE = 0
    RUNNING = 1
    STOPPED = 2
    FINISHED = 3
    ERROR = 4

@dataclass
class DeviceState:
    schedule: Schedule
    device: Device
    current_task: Task = None
    state: RunningState = RunningState.PREPARE
    progress: float = 0


class _Worker:

    def __init__(self, robot:Robot, task_list:list[tuple[Task, BaseTask, list]]) -> None:
        self.robot = robot
        self.task_list = task_list
        self.thread = Thread(target=self.run)
        self.state = RunningState.PREPARE
        self.current_task = task_list[0][0]
        self.stoped = False
    
    def run(self):
        self.state = RunningState.RUNNING
        for task, cls, args in self.task_list:
            if self.stoped:
               self.state = RunningState.STOPPED
               return
            self.current_task = task
            self.robot._run_task(task.name, cls, args)
        self.state = RunningState.FINISHED
        self.current_task = None


    def start(self):
        if self.state == RunningState.FINISHED or self.state == RunningState.STOPPED:
            self.thread = Thread(target=self.run)
        self.thread.start()

    def stop(self):
        self.stoped = True

class _WorkerManager:
    
    def assign_schedule(self, device:Device, schedule:Schedule)->_Worker:
        robot = Robot(device.driver, show_progress=False)
        task_list = []
        for task in schedule.tasks:
            task_list.append((task,*taskRepository.convert_to_real_task(task)))
        return _Worker(robot, task_list)


class _DeviceRuntime:

    def __init__(self) -> None:
        self.state:dict[str, DeviceState] = {}
        self.worker:dict[str, _Worker] = {}
        self.worker_manager = _WorkerManager()
        self.callback = None
        self.refresh_thread = None
    
    def set_listener(self, callback):
        self.callback = callback
    
    def on_refresh(self):
        while True:
            time.sleep(5)
            for k,worker in self.worker.items():
                if k in self.state:
                    self.state[k].state = worker.state
                    self.state[k].current_task = worker.current_task
            if self.callback:
                self.callback()
            has_active_worker = False
            for worker in self.worker.values():
                if worker.state == RunningState.RUNNING:
                    has_active_worker = True
                    break
            if not has_active_worker:
                break
        self.refresh_thread = None
    
    def _key(self, device: Device):
        return f"{device.name}-{device.device_type}"

    def get_running_state(self, device:Device) -> DeviceState|None:
        return self.state.get(self._key(device), None)

    def assign_schedule(self, device:Device, schedule:Schedule):
        k = self._key(device)
        worker = self.worker_manager.assign_schedule(device, schedule)
        self.worker[k] = worker
        self.state[k] = DeviceState(schedule=schedule, device=device)

    def start_schedule(self, device:Device, schedule:Schedule):
        k = self._key(device)
        if k not in self.worker or self.worker[k].state == RunningState.RUNNING:
            print("分配了无效的任务列表")
            return
        self.state[k] = DeviceState(schedule=schedule, device=device, current_task=schedule.tasks[0], state=RunningState.RUNNING)
        self.worker[k].start()
        if not self.refresh_thread:
            self.refresh_thread = Thread(target=self.on_refresh)
            self.refresh_thread.start()

    def stop_schedule(self, device:Device):
        k = self._key(device)
        if k in self.worker:
            self.worker[k].stop()
            self.state[k] = DeviceState(schedule=None, device=device, state=RunningState.STOPPED)
    

device_runtime = _DeviceRuntime()