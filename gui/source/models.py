from dataclasses import dataclass
from pcrscript.driver import Driver
from enum import IntEnum
from pydantic import BaseModel, Field
from typing import Optional
import uuid

class SourceType(IntEnum):
    General = 1
    Leidian = 2
    MuMu12 = 3

@dataclass
class Device:
    name: str
    device_type: str
    driver: Driver

class Task(BaseModel):
    name: str
    desc: Optional[str]

class Schedule(BaseModel):
    id: str = Field(default_factory=lambda : str(uuid.uuid4()))
    name: str = id
    tasks: list[Task] = []
