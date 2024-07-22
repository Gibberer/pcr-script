from .models import Task
from pcrscript.tasks import BaseTask

class _TaskRepository:
    
    def __init__(self) -> None:
        from pcrscript.tasks import _registedTasks
        self.real_task_dict = _registedTasks
    
    def get_tasks(self) -> list[Task]:
        result = []
        for name,cls in self.real_task_dict.items():
            desc = None
            if cls.__doc__:
                desc = cls.__doc__.strip()
            result.append(Task(name=name, desc=desc))
        return result
    
    def convert_to_real_task(self, task:Task) -> tuple[BaseTask,list]:
        cls = self.real_task_dict.get(task.name, None)
        if cls:
            return cls, None
        else:
            return None, None

    
taskRepository = _TaskRepository()