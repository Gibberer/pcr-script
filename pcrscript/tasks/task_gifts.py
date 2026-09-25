"""Gift collection with bounded EX inventory recovery using saved game settings."""
from __future__ import annotations
from .registry import register
import json
from typing import TYPE_CHECKING
from .base import BaseTask, TaskOptions, TaskReport
from ..game_ui.screen import EventScreen
if TYPE_CHECKING:
    from pcrscript import Robot
from pcrscript.run_session import clock as time

import cv2 as cv
import numpy as np

from ..game_ui.screen import EventUI, EventUIError, normalized


def inventory(screen: EventScreen) -> tuple[int, int]:
    item = screen.find(r"\d+/\d+", (495, 65, 605, 103), exact=True)
    if item is None or item.score < .95:
        raise EventUIError("特别装备持有数无法确认")
    used, capacity = map(int, normalized(item.text).split("/"))
    if not 0 <= used <= capacity or capacity == 0:
        raise EventUIError("特别装备持有数不合法")
    return used, capacity


def stamina_excluded(screen: EventScreen) -> bool:
    # Checkbox tick is blue; the unchecked box has a white/gray interior.
    hsv = cv.cvtColor(screen.image[458:492, 343:379], cv.COLOR_BGR2HSV)
    return bool(np.mean((hsv[:, :, 0] > 85) & (hsv[:, :, 0] < 120)
                        & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 180)) > .12)


@register("get_gift")
class GetGift(BaseTask):
    config_section = 'Gift'
    config_attribute = 'gift_options'

    def __init__(self, robot: Robot, options: TaskOptions | None = None) -> None:
        super().__init__(robot)
        self.options = self.task_options() if options is None else options
        self.ui = EventUI(robot.driver, self.options.get("output", "cache/daily/gifts"))
        self.target = int(self.options.get("free_slots", 750))
        if not 500 <= self.target <= 1000:
            raise ValueError("Gift.free_slots 必须为 500～1000")
        self.deadline = time.monotonic() + self.options.get("timeout", 900)
        self.report: TaskReport = {"status": "running", "gift_batches": 0, "dismantled": 0,
                       "inventory": [], "pending": []}

    def check(self) -> None:
        if time.monotonic() > self.deadline:
            raise EventUIError("礼物任务达到总运行时间上限")

    def home(self) -> EventScreen:
        # Recover only recognized interrupted dialogs. Never accept a pending
        # dismantle/collection proposal just to navigate to the home page.
        for _ in range(5):
            s = self.ui.capture()
            if s.find("持有上限", (240, 100, 720, 175), exact=True):
                self.ui.expect_click("确认", (350, 330, 615, 405), exact=True)
            elif s.find("收取礼物", (240, 20, 720, 70), exact=True):
                if s.find("收取了以下道具", (250, 65, 715, 102)):
                    self.ui.expect_click("确认", (360, 440, 605, 515), exact=True)
                else:
                    self.ui.expect_click("取消", (250, 440, 480, 515), exact=True)
            elif s.find("特别装备分解确认", (240, 20, 720, 70), exact=True):
                self.ui.expect_click("关闭", (250, 440, 480, 515), exact=True)
            elif s.find("回收结果", (240, 20, 720, 70), exact=True):
                self.ui.expect_click("确认", (360, 440, 605, 515), exact=True)
            elif s.find("礼物箱", (300, 20, 660, 65), exact=True):
                self.ui.expect_click("取消", (475, 440, 700, 515), exact=True)
            else:
                break
        self.ui.click((77, 525))
        return self.ui.wait(lambda s: s.find("商店", (645, 400, 735, 475), exact=True)
                            and s.find("礼物", (860, 400, 950, 475), exact=True), "返回首页")

    def gift_list(self) -> EventScreen:
        return self.ui.wait(lambda s: s.find("礼物箱", (300, 20, 660, 65), exact=True)
                            and not s.find("持有上限|收取礼物|收取结果|收取完成", (240, 20, 720, 175)), "礼物列表")

    def open_gifts(self, exclude_stamina: bool) -> EventScreen:
        s = self.home()
        self.ui.click(s.find("礼物", (860, 400, 950, 475), exact=True))
        s = self.gift_list()
        if not s.find("除体力外", (375, 440, 475, 502)):
            raise EventUIError("未识别礼物排除体力选项")
        if stamina_excluded(s) != exclude_stamina:
            self.ui.click((361, 476))
            s = self.gift_list()
            if stamina_excluded(s) != exclude_stamina:
                raise EventUIError("礼物体力选项切换失败")
        return s

    def dismantle_button(self, screen: EventScreen):
        if not screen.find("道具一览", (30, 0, 220, 60)):
            return None
        roi = (750, 0, 950, 60)
        return (screen.find("一键分解", roi, exact=True)
                or self.ui.read_region(screen, roi).find("一键分解", roi, exact=True))

    def free_space(self, require_full: bool = False) -> bool:
        """Only auto-dismantle via the game's saved rules; never touch settings.

        Live 2026-09-12: one automatic batch removes 50 items. Read inventory
        after every result; a changed batch size stops further dismantling.
        """
        s = self.home()
        self.ui.click(s.find("商店", (645, 400, 735, 475), exact=True))
        self.ui.expect_click("特别装备", (595, 50, 700, 95), exact=True)
        self.ui.expect_click("特别装备分解", (780, 410, 950, 465), exact=True)
        for batch in range(21):
            self.check()
            s = self.ui.wait(self.dismantle_button, "特别装备库存")
            before, capacity = inventory(s)
            self.report["inventory"].append({"used": before, "capacity": capacity})
            self.ui.save(f"inventory_{batch}", s)
            if batch == 0 and require_full and before < capacity:
                self.report["pending"].append("礼物提示持有上限，但特别装备未满；未执行分解，请检查其他道具")
                self.home()
                return False
            if capacity - before >= self.target:
                self.home()
                return True
            if batch == 20 or self.report["dismantled"] + 50 > 1000:
                self.report["pending"].append("本轮特别装备分解已达到数量上限")
                self.home()
                return False
            button = self.dismantle_button(s)
            if button is None:
                raise EventUIError("一键分解按钮无法确认")
            self.ui.click(button)
            self.ui.expect_click("自动(?:分解)?", (615, 350, 765, 415), exact=True)
            s = self.ui.wait(lambda s: s.find("特别装备分解确认|没有.*(装备|道具)|无.*(装备|道具)|自动分解对象|分解的.*不存在"), "自动分解确认")
            if not s.find("特别装备分解确认", (250, 20, 720, 70), exact=True):
                self.ui.save("no_auto_candidates", s)
                self.report["pending"].append("游戏已有自动分解规则没有可分解对象，请用户检查设置")
                return False
            self.ui.save(f"auto_plan_{batch}", s)
            roi = (485, 450, 695, 509)
            button = s.find("分解", roi, exact=True)
            if button is None:
                button = self.ui.read_region(s, roi).find("分解", roi, exact=True)
            if button is None or not s.blue_button(button):
                raise EventUIError("无法确认自动分解确认按钮")
            self.ui.click(button)
            self.ui.wait(lambda s: s.find("回收结果", (250, 20, 720, 70), exact=True), "分解结算")
            self.ui.expect_click("确认", (360, 440, 605, 515), exact=True)
            s = self.ui.wait(self.dismantle_button, "分解后库存")
            after, new_capacity = inventory(s)
            removed = before - after
            self.report["dismantled"] += max(0, removed)
            print(f"[礼物] 自动分解 {removed} 件，库存 {after}/{new_capacity}", flush=True)
            if new_capacity != capacity or not 0 < removed <= 50:
                raise EventUIError("自动分解数量与已验证的每批 1～50 件不符，停止后续分解")
        return False

    def run(self, exclude_stamina: bool = True) -> TaskReport:
        recovered = False
        try:
            self.open_gifts(exclude_stamina)
            for batch in range(int(self.options.get("max_gift_batches", 30))):
                self.check()
                s = self.gift_list()
                button = s.find("全部收取", (700, 440, 930, 515), exact=True)
                if not button or not s.blue_button(button):
                    if s.find("没有.*礼物|无.*礼物|未.*礼物") or button:
                        self.report["status"] = "complete"
                        self.ui.expect_click("取消", (475, 440, 700, 515), exact=True)
                        return self.report
                    raise EventUIError("无法确认礼物箱是否已收取完毕")
                self.ui.click(button)
                self.ui.wait(lambda s: s.find("收取礼物", (240, 20, 720, 70), exact=True), "收取确认")
                self.ui.expect_click("确认", (480, 440, 710, 515), exact=True)
                # Confirmation and success share the same title. The success
                # body and single centered OK distinguish it from a proposal.
                s = self.ui.wait(lambda s: s.find("持有上限|收取结果|收取完成", (240, 20, 720, 175))
                                 or s.find("收取了以下道具", (250, 65, 715, 102)), "礼物收取结果")
                self.ui.save(f"gift_result_{batch}", s)
                if s.find("持有上限", (240, 100, 720, 175), exact=True):
                    self.ui.expect_click("确认", (350, 330, 615, 405), exact=True)
                    self.gift_list()
                    self.ui.expect_click("取消", (475, 440, 700, 515), exact=True)
                    if recovered or not self.options.get("auto_dismantle", True):
                        self.report["pending"].append("礼物仍受持有上限阻塞，本轮不再分解")
                        break
                    recovered = True
                    if not self.free_space(require_full=True):
                        break
                    self.open_gifts(exclude_stamina)
                else:
                    self.report["gift_batches"] += 1
                    self.ui.expect_click("确认", (300, 350, 710, 515), exact=True)
            else:
                self.report["pending"].append("礼物领取达到批次上限，下次继续")
            self.report["status"] = "partial"
            return self.report
        except Exception as error:
            from pcrscript.run_session import failure
            failure(error)
            self.report["status"] = "error"
            self.report["pending"].append(str(error))
            self.ui.save("error")
            raise
        finally:
            (self.ui.output / "report.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[礼物] {self.report['status']}；" + "；".join(self.report["pending"]), flush=True)
