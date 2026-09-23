"""The single registry shared by every task entry point."""
from typing import Callable, TypeVar
from .base import BaseTask

TaskType = TypeVar('TaskType', bound=type[BaseTask])
_registedTasks: dict[str, type[BaseTask]] = {}

def find_taskclass(name: str) -> type[BaseTask] | None:
    '''
    根据名称获取task类
    '''
    return _registedTasks.get(name, None)


def registered_tasks() -> tuple[str, ...]:
    return tuple(sorted(_registedTasks))


def register(name: str, *, requires_home: bool = False) -> Callable[[TaskType], TaskType]:
    def wrap(cls: TaskType) -> TaskType:
        if name in _registedTasks:
            raise Exception(f"Task:{name} already registed.")
        _registedTasks[name] = cls
        cls.name = name
        cls.requires_home = requires_home
        return cls
    return wrap
