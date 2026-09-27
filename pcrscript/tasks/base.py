from abc import ABCMeta, abstractmethod
import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, NotRequired, Optional, TypeAlias, TypedDict
import numpy as np
from numpy.typing import NDArray
from ..run_session import clock as time
from ..run_session import emit
if TYPE_CHECKING:
    from pcrscript import Robot

TaskOptions: TypeAlias = dict[str, Any]
TaskReport: TypeAlias = dict[str, Any]
TaskConfig: TypeAlias = dict[str, Any]
PreparedTask: TypeAlias = tuple[tuple[Any, ...], dict[str, Any], TaskReport | None]
Point: TypeAlias = tuple[int, int]
Region: TypeAlias = tuple[int, int, int, int]
Screenshot: TypeAlias = NDArray[np.uint8]


class TaskExecutionRecord(TypedDict):
    task: str
    status: str
    report: NotRequired[Any]  # Legacy task methods may return values other than reports.
    error: NotRequired[str]
    duration_seconds: NotRequired[float]

class BaseTask(metaclass=ABCMeta):
    """Recognition-independent task contract, configuration and runtime context."""

    config_section: ClassVar[str | None] = None
    config_attribute: ClassVar[str | None] = None
    requires_home: ClassVar[bool] = False
    name: ClassVar[str]

    def task_options(self) -> TaskOptions:
        """One configuration path for daily dispatch and standalone commands."""
        config = getattr(self.robot, 'task_config', {})
        legacy = getattr(self.robot, self.config_attribute, {}) if self.config_attribute else {}
        options = copy.deepcopy(config.get(self.config_section, legacy) if self.config_section else legacy)
        output = getattr(self.robot, '_task_output', None)
        if output is not None:
            options['output'] = str(output)
        return options

    @classmethod
    def prepare(cls, config: TaskConfig, *args: Any, **kwargs: Any) -> PreparedTask:
        """Read-only preflight may return a report before connecting a device."""
        return args, kwargs, None

    def __init__(self, robot: 'Robot') -> None:
        self.robot = robot
        self.driver = robot.driver

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        return self.run(*args, **kwds)

    def report_progress(self, label: str, current: int | None = None,
                        total: int | None = None) -> None:
        """Publish a business milestone without depending on image actions.

        Unknown-length OCR work reports a label with an indeterminate bar.
        Counts describe a bounded batch, not a claim that the game is complete.
        """
        if not label or not isinstance(label, str):
            raise ValueError('进度说明不能为空')
        if (current is None) != (total is None):
            raise ValueError('进度计数与总数必须同时提供')
        if total is not None and (not isinstance(total, int) or isinstance(total, bool)
                                  or not isinstance(current, int) or isinstance(current, bool)
                                  or total < 1 or not 0 <= current <= total):
            raise ValueError('进度必须满足 0 ≤ 当前数 ≤ 正整数总数')
        data = {'label': label, 'unit': 'task'}
        if total is not None:
            data.update(current=current, total=total)
        emit('progress', scope='action', **data)

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> Any:
        pass


@dataclass
class Event:
    startTimestamp: float
    endTimestamp: float
    name: str
    extras: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        start = time.localtime(self.startTimestamp)
        end = time.localtime(self.endTimestamp)
        return (
            f"{self.name}:{start.tm_mon}/{start.tm_mday} - {end.tm_mon}/{end.tm_mday}"
        )


@dataclass
class EventNews:
    freeGacha: Optional[Event] = None  # 免费扭蛋
    tower: Optional[Event] = None  # 露娜塔
    dropItemNormal: Optional[Event] = None  # 普通关卡掉落活动
    dropItemHard: Optional[Event] = None # 困难关卡掉落活动
    hatsune: Optional[Event] = None  # 剧情活动
    clanBattle: Optional[Event] = None  # 公会战
    secretDungeon: Optional[Event] = None # 特别地下城
    revival: Optional[Event] = None # 单独查询复刻，避免与同期新活动互相覆盖


class TimeLimitTask(BaseTask):
    '''
    时限任务
    '''

    @staticmethod
    @abstractmethod
    def valid(event_news: EventNews, args: list[Any] | None = None) -> tuple[type[BaseTask], list[Any] | None] | None:
        pass

    @staticmethod
    def event_valid(event: Event | None) -> bool:
        if not event:
            return False
        return event.startTimestamp <= time.time() <= event.endTimestamp

    @staticmethod
    def event_first_day(event: Event | None) -> bool:
        if not event:
            return False
        current_time = time.time()
        if current_time > event.startTimestamp:
            return (
                time.localtime(current_time).tm_mday
                == time.localtime(event.startTimestamp).tm_mday
            )
        return False

    @staticmethod
    def event_last_day(event: Event | None) -> bool:
        if not event:
            return False
        return 0 < event.endTimestamp - time.time() < 86400
