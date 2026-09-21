"""Template/action capabilities for image-driven tasks only."""
from __future__ import annotations

from typing import TYPE_CHECKING
from ..actions import Action
from ..constants import BASE_WIDTH, BASE_HEIGHT
from ..templates import Template
from .base import BaseTask, Point, Region, Screenshot

if TYPE_CHECKING:
    from pcrscript import Robot


class ImageTask(BaseTask):
    """Legacy action sequences, template coordinates and progress tracking."""

    def __init__(self, robot: Robot) -> None:
        super().__init__(robot)
        self.define_width: int = BASE_WIDTH
        self.define_height: int = BASE_HEIGHT
        self.num_step: int = 1
        self.total_step: int | str = 1
        self.show_progress: bool = True

    def set_progress(self, total_step: int | str = 1, num_step: int = 1, show_progress: bool = True) -> None:
        self.total_step = total_step
        self.num_step = num_step
        self.show_progress = show_progress

    def action_squential(self, *actions: Action, show_progress: bool | None = None, net_error_check: bool = True, title: str | None = None) -> None:
        for action in actions:
            action.bindTask(self)
        if show_progress is None:
            show_progress = self.show_progress
        self.robot.action_squential(*actions, net_error_check=net_error_check, show_progress=show_progress, progress_index=self.num_step, total_step=self.total_step, title=title)
        self.num_step += 1

    def action_once(self, action: Action) -> bool:
        action.bindTask(self)
        action.do(self.robot.driver.screenshot(), self.robot)
        return action.done()

    def template_match(self, screenshot: Screenshot, template: Template) -> Point | None:
        template.set_define_size(self.define_width, self.define_height)
        return template.match(screenshot)

    def in_region(self, r: Region, pos: Point) -> bool:
        return (r[0] < pos[0] < r[2]) and (r[1] < pos[1] < r[3])

    def center_region(self, r: Region) -> Point:
        return (int((r[0]+r[2])/2), int((r[1]+r[3])/2))

    def adapted_region(self, r: Region, w: int, h: int) -> Region:
        hscale = w/self.define_width
        vscale = h/self.define_height
        return (int(r[0]*hscale), int(r[1]*vscale), int(r[2]*hscale), int(r[3]*vscale))
