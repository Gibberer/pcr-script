"""One bulk sweep for the three event hard stages; no quest-map audit."""
import time

from ..game_ui.screen import EventUIError, normalized


HARD_STAGES = {f"活动关卡H-{i}" for i in (1, 2, 3)}


def hard_rows(screen):
    return {normalized(row.text): row for row in
            screen.all(r"活动关卡H-[123]", (35, 135, 350, 375))}


def attempts(screen, row):
    y = row.center[1]
    item = screen.find(r"[0-3]/3", (435, y, 495, min(y+48, 378)), exact=True)
    return int(normalized(item.text)[0]) if item else None


class HardSweep:
    def __init__(self, runner):
        self.r = runner
        self.ui = runner.ui

    def stable_list(self):
        return self.ui.wait(lambda s: s.find("关卡一览", (300, 0, 700, 70))
                            and not s.find("未勾选任何关卡|正在进行数据连接"), "困难扫荡列表")

    def leave(self, pending=None):
        self.ui.expect_click("取消", (460, 440, 710, 520), exact=True)
        self.ui.wait(lambda s: s.event_quests, "返回活动关卡")
        if pending:
            self.r.report["pending"].append(pending)
        return pending is None

    def run(self):
        self.r.check_deadline()
        self.r.quests()
        self.ui.expect_click("扫荡", (790, 95, 940, 150), exact=True)
        s = self.stable_list()
        # Usually all three H rows are already visible. Only scroll if the
        # sweeper remembers a different position; never walk the N/H map.
        for _ in range(4):
            rows = hard_rows(s)
            if set(rows) == HARD_STAGES:
                break
            self.ui.swipe((700, 165), (700, 345))
            s = self.stable_list()
        else:
            return self.leave("困难扫荡尚未完整开放/无法定位，跳过首通并继续领奖")
        remaining = {name: attempts(s, row) for name, row in rows.items()}
        if any(value is None for value in remaining.values()):
            # A transient label may obscure one counter. One fresh frame is
            # enough to retry; unknown counts never authorize spending.
            s = self.stable_list()
            rows = hard_rows(s)
            remaining = {name: attempts(s, rows[name]) if name in rows else None for name in HARD_STAGES}
        if any(value is None for value in remaining.values()):
            return self.leave("困难关卡剩余次数无法确认，跳过扫荡并继续领奖")
        plan = {name: count for name, count in remaining.items() if count > 0}
        if not plan:
            self.r.log("三个困难关卡今日次数已用完")
            return self.leave()
        clear = s.find("解除所有勾选", (740, 75, 920, 140), exact=True)
        if clear:
            self.ui.click(clear)
            s = self.stable_list()
        elif not s.find("全部勾选|勾选全部", (740, 75, 920, 140)):
            return self.leave("无法清除上次扫荡选择，跳过扫荡并继续领奖")
        rows = hard_rows(s)
        if not plan.keys() <= rows.keys():
            return self.leave("困难扫荡列表发生变化，停止勾选")
        for name in sorted(plan, reverse=True):
            self.ui.click((851, rows[name].center[1]+16), delay=.2)
        # A shared multiplier of 3 normally clears all three stages together.
        # If some attempts were already spent, the final preview must show
        # exactly the remaining counts for each selected stage.
        target = max(plan.values())
        for _ in range(4):
            s = self.ui.capture()
            current = self.ui.number(s, (775, 395, 840, 436))
            if current is None or not 1 <= current <= 99:
                return self.leave("扫荡次数无法确认，停止扫荡并继续领奖")
            if current == target:
                break
            for _ in range(abs(current-target)):
                self.ui.click((885 if current < target else 733, 413), delay=.1)
        else:
            return self.leave("扫荡次数未能设置，停止扫荡并继续领奖")
        if s.find("体力不足", (35, 440, 470, 500)):
            return self.leave("体力不足以完成困难批量扫荡，继续领奖；未购买体力")
        button = s.find("一键扫荡", (700, 440, 920, 520), exact=True)
        if button is None or not s.blue_button(button):
            return self.leave("困难批量扫荡不可用，继续领奖")
        self.ui.save("hard_bulk_plan", s)
        self.ui.click(button)
        self.settle(plan)
        self.r.log("一键扫荡 " + "、".join(f"{name} × {count}" for name, count in sorted(plan.items())))

    def settle(self, plan):
        confirmed = False
        for _ in range(40):
            self.r.check_deadline()
            s = self.ui.capture()
            if s.find("正在.*连接|数据连接|加载中|下载中", (0, 0, 960, 100)):
                time.sleep(.5)
                continue
            if s.find("一?键扫荡确认", (250, 0, 710, 70)):
                if confirmed:
                    time.sleep(.5)
                    continue
                rows = s.all(r"活动关卡[HN]-\d+", (35, 90, 360, 335))
                actual = {}
                for row in rows:
                    y = row.center[1]
                    actual[normalized(row.text)] = self.ui.number(s, (830, y+3, 925, y+48))
                spend = self.ui.number(s, (225, 340, 265, 375))
                if len(rows) != len(plan) or actual != plan or spend != sum(plan.values())*20:
                    self.ui.save("hard_bulk_mismatch", s)
                    raise EventUIError("困难批量扫荡确认与勾选计划不符，未确认消费")
                self.ui.save("hard_bulk_confirm", s)
                button = s.find("挑战", (460, 445, 720, 520), exact=True)
                if button:
                    self.ui.click(button)
                    confirmed = True
            elif confirmed and s.find("关卡一览", (300, 0, 700, 70)):
                rows = hard_rows(s)
                if any(name not in rows or attempts(s, rows[name]) != 0 for name in plan):
                    raise EventUIError("困难批量扫荡后次数未能核实，停止重复消费")
                self.ui.save("hard_bulk_finished", s)
                self.leave()
                return
            elif s.find("扫荡结果|获得道具|扫荡完成|扫荡券使用结果"):
                button = s.find("全部跳过|跳过|确认|确定|关闭|OK", (200, 300, 950, 535), exact=True)
                if button:
                    self.ui.click(button)
            elif s.find("限定商店|限时商店"):
                self.ui.expect_click("取消|关闭", (200, 300, 800, 525), exact=True)
            elif s.find("体力回复|体力恢复|购买体力"):
                self.ui.expect_click("取消", (200, 300, 800, 520), exact=True)
                raise EventUIError("扫荡请求购买体力，已取消")
            else:
                time.sleep(.5)
        raise EventUIError("困难批量扫荡结算超时，停止重复消费")
