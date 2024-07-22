import os
from pathlib import Path
from gui.source.models import Schedule
from pydantic import TypeAdapter

KEY_SELECTED_SOURCES = "SELECTED_SOURCES"

class KVStorage:
    @classmethod
    def init(cls, client_storage):
        cls._storage = client_storage
    @classmethod
    def get(cls, key:str):
        return cls._storage.get(key)
    @classmethod
    def set(cls, key:str, value):
        cls._storage.set(key, value)

class _ScheduleStorage:
    
    def __init__(self) -> None:
        self.assets = os.getenv("FLET_ASSETS_DIR")
        self.schedules_path = Path(self.assets)/'schedules.conf'
        self.schedules = []
        self.adapter = TypeAdapter(list[Schedule])
    
    def get_schedule_list(self) -> list[Schedule]:
        if self.schedules:
            return self.schedules
        if self.schedules_path.exists():
            with self.schedules_path.open(encoding="utf-8") as f:
                self.schedules = self.adapter.validate_json(f.read())
            return self.schedules
        else:
            return []

    def save_schedule(self, schedule:Schedule):
        if self.schedules:
            found = False
            for i,s in enumerate(self.schedules):
                if s.id == schedule.id:
                    self.schedules[i] = schedule
                    found = True
                    break
            if not found:
                self.schedules.append(schedule)
        else:
            self.schedules = [schedule]
        self.save_schedules(self.schedules)
    
    def remove_schedule(self, schedule:Schedule):
        if not self.schedules:
            self.get_schedule_list()
        if not self.schedules:
            return
        for i,s in enumerate(self.schedules):
            if s.id == schedule.id:
                self.schedules.pop(i)
                break
        self.save_schedules(self.schedules)

    def save_schedules(self, schedules:list[Schedule]):
        self.schedules = schedules
        if not os.path.exists(self.assets):
            os.mkdir(self.assets)
        with self.schedules_path.open(mode="wb") as f:
            f.write(self.adapter.dump_json(self.schedules))

schedule_storage = _ScheduleStorage()