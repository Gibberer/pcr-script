"""List-layout story-event workflow, reusable for new and revival editions."""
import json
import re
import time

from ..game_ui.screen import EventUI, EventUIError, normalized


class StoryEventRunner:
    def __init__(self, robot, options=None):
        self.robot = robot
        self.options = options or {}
        self.ui = EventUI(robot.driver, self.options.get("output", "cache/daily/story_event"))
        self.report = {"status": "running", "steps": [], "pending": [], "battles": []}
        self.deadline = time.monotonic() + self.options.get("timeout", 1800)

    def log(self, message):
        print(f"[剧情活动] {message}", flush=True)
        self.report["steps"].append(message)

    def check_deadline(self):
        if time.monotonic() > self.deadline:
            raise EventUIError("活动任务达到总运行时间上限")

    def entry_dialog(self, s):
        """Dismiss the daily event login receipt, not an arbitrary reward modal."""
        title_roi = (240, 110, 720, 185)
        if not s.find("获得活动登录奖励", title_roi, exact=True):
            return False
        close = s.find("关闭", (350, 330, 615, 410), exact=True)
        if close is None:
            raise EventUIError("活动登录奖励弹窗的关闭按钮无法识别")
        self.ui.save("event_login_reward", s)
        self.ui.click(close)
        self.ui.wait(lambda frame: not frame.find("获得活动登录奖励", title_roi, exact=True), "关闭活动登录奖励")
        self.log("已关闭活动每日登录奖励弹窗")
        return True

    def story_dialog(self, s):
        """Only story-specific controls, never a global 'OK' clicker."""
        if s.find("剧情梗概|跳过这个剧情|跳过剧情吗|跳过这个视频"):
            item = s.find("跳过", (460, 300, 720, 500), exact=True)
        elif s.find("语音|声音数据"):
            item = s.find("不下载|无语音|不含语音")
        elif s.find("全文显示|快进|记录", (680, 70, 960, 380)):
            item = s.find("跳过", (700, 70, 960, 220), exact=True)
        elif s.find("菜单", (840, 0, 960, 100)) and not s.find("主菜单"):
            item = s.find("菜单", (840, 0, 960, 100), exact=True)
        elif s.find("报酬确认|获得报酬|获得奖励|剧情解锁|解锁了|新剧情"):
            item = s.find("确认|确定|关闭|跳过", (200, 300, 800, 525), exact=True)
        else:
            item = None
        if item:
            self.ui.click(item)
            return True
        if s.find("Cygames|アニメーション|エンディング") or (len(s.items) < 8 and s.find(".+", (250, 440, 860, 525))
                and not s.find("加载中|下载中|连接|取消|确认|关闭|获得|报酬|确定")
                and not s.find(".+", (0, 0, 960, 100))):
            # Movie captions with no page chrome. The game's top-right skip
            # hotspot opens a confirmation even while its overlay is hidden.
            self.ui.click((898, 45))
            return True
        return False

    def enter(self):
        """Use live navigation even if the downloaded calendar is outdated."""
        missing_entry = 0
        for _ in range(90):
            self.check_deadline()
            s = self.ui.capture()
            if self.entry_dialog(s):
                continue
            if s.find("角色详情", (300, 0, 700, 70)):
                self.ui.expect_click("确认", (320, 450, 650, 515), exact=True)
                continue
            if self.story_dialog(s):
                continue
            if s.event_home and not s.find("关卡.*首领", (0, 300, 260, 460)):
                self.ui.save("unsupported_event", s)
                self.log("当前为旧版或未适配的活动首页，跳过新版活动任务")
                return False
            if s.event_home or s.event_quests or s.find("报酬[交兑]换|回忆录|艾拉的世界|诗夏的世界", (0, 0, 300, 65)) or s.find("BOSS详情|队伍编组", (0, 0, 730, 70)):
                self.ui.save("event_entry", s)
                return True
            if s.find("关卡一览", (300, 0, 700, 70)):
                self.ui.expect_click("取消", (460, 440, 710, 520), exact=True)
            elif s.find("一?键扫荡确认", (250, 0, 710, 70)):
                # A previous run stopped before confirming a spend. Cancel it
                # and rebuild the plan from current counts, never blindly resume.
                self.ui.expect_click("取消", (250, 440, 480, 520), exact=True)
            elif s.story_list or s.find("活动任务", (0, 0, 280, 65)):
                self.ui.click((32, 30))
            elif s.find("主线关卡", (45, 0, 240, 65), exact=True):
                # The main-quest map has the same words as the adventure-menu
                # card. Its missing event button does not mean no event exists.
                self.ui.click((32, 30))
            elif s.find("主线关卡"):
                entry = s.find("剧情活动", (0, 250, 500, 465))
                if entry:
                    missing_entry = 0
                    self.ui.click(entry)
                else:
                    missing_entry += 1
                    if missing_entry >= 3:
                        self.log("冒险页面没有可见剧情活动入口，本轮跳过")
                        return False
                    time.sleep(1)
            elif s.find("冒险", (460, 470, 600, 540), exact=True):
                self.ui.click(s.find("冒险", (460, 470, 600, 540), exact=True))
            elif s.find("活动举办的通知"):
                self.ui.click(s.find("关闭", (300, 420, 650, 530), exact=True))
            elif s.find("活动尚未|活动未开放|活动已结束"):
                self.log("当前活动未开放")
                return False
            else:
                time.sleep(1)
        self.ui.save("unrecognized_entry")
        raise EventUIError("无法进入列表式剧情活动；地图布局不使用列表坐标")

    def home(self):
        for _ in range(45):
            s = self.ui.capture()
            if self.entry_dialog(s):
                continue
            if s.event_home:
                return s
            if s.find("角色详情", (300, 0, 700, 70)):
                self.ui.expect_click("确认", (320, 450, 650, 515), exact=True)
                continue
            if s.event_quests or s.story_list or s.find("活动任务|报酬[交兑]换|回忆录|艾拉的世界|诗夏的世界", (0, 0, 350, 70)):
                self.ui.click((32, 30))
            elif s.find("关卡一览", (300, 0, 700, 70)):
                self.ui.expect_click("取消", (460, 440, 710, 520), exact=True)
            elif s.find("BOSS详情|关卡详情|队伍编组", (0, 0, 730, 70)):
                self.ui.expect_click("取消", (550, 420, 950, 520), exact=True)
            elif not self.story_dialog(s):
                time.sleep(.7)
        raise EventUIError("未能返回活动首页")

    def quests(self, bosses=False):
        s = self.ui.capture()
        if not s.event_quests:
            s = self.home()
            item = s.find("关卡.*首领", (0, 300, 260, 460))
            if not item:
                raise EventUIError("检测到旧版或未知活动布局，停止使用新版流程")
            self.ui.click(item)
            self.ui.wait(lambda s: s.event_quests, "活动关卡入口")
        self.ui.expect_click("首领战" if bosses else "活动关卡", (450, 55, 950, 95), exact=True)
        return self.ui.wait(lambda s: bool(s.find("剧本模式|特别", (700, 150, 940, 440))) if bosses
                            else bool(s.find(r"活动关卡[HN]-\d", (460, 140, 920, 465))), "关卡列表")

    def stories(self):
        s = self.home()
        if not s.notification((692, 355, 738, 402)):
            self.log("活动剧情入口无未领取提示，跳过")
            return
        self.ui.click(s.find("活动剧情", (650, 280, 960, 465)))
        self.ui.wait(lambda s: s.story_list, "活动剧情列表")
        read_count = 0
        idle = 0
        unchanged = None
        for _ in range(300):
            self.check_deadline()
            s = self.ui.capture()
            if self.story_dialog(s):
                idle = 0
                continue
            if s.find("加载中|下载中|数据连接"):
                # Event movies can download hundreds of MB. The task-wide
                # deadline still bounds a stalled transfer.
                time.sleep(1)
                continue
            if s.story_list:
                new = s.find("新内容|NEW|未读", (100, 55, 920, 490))
                if new:
                    self.ui.save(f"story_{read_count:02d}", s)
                    self.log(f"打开未读剧情：{s.text((100, 70, 900, 460))}")
                    self.ui.click((new.center[0] + 70, new.center[1] + 40))
                    read_count += 1
                    idle = 0
                    unchanged = None
                    continue
                signature = s.text((0, 55, 940, 490))
                idle = idle+1 if signature == unchanged else 0
                unchanged = signature
                if idle >= 2:
                    self.ui.click((32, 30))
                    self.log(f"活动剧情本轮打开 {read_count} 篇，未再发现可读新剧情")
                    return
                self.ui.swipe((830, 150), (830, 435))
            elif s.event_home:
                # Some events return home and unlock the next story there.
                if not s.notification((692, 355, 738, 402)):
                    self.log("活动剧情入口提示已清除")
                    return
                self.ui.click(s.find("活动剧情", (650, 280, 960, 465)))
            elif s.find("下载", (200, 300, 750, 480)) and s.find("剧情|语音"):
                self.ui.expect_click("不下载|无语音|不含语音")
            else:
                idle += 1
                if idle > 12:
                    self.ui.save("story_unknown")
                    raise EventUIError("剧情出现未知分支，已保存截图")
                time.sleep(1)
        raise EventUIError("剧情读取达到步骤上限")

    def missions(self):
        s = self.home()
        if not s.notification((787, 3, 832, 45)):
            self.log("活动任务入口无可领取提示，跳过")
            return
        self.ui.click(s.find("任务", (700, 0, 840, 85), exact=True))
        self.ui.wait(lambda s: s.find("活动任务", (0, 0, 280, 65)), "活动任务")
        for tab in ("每日", "普通", "特别", "称号"):
            self.ui.expect_click(tab, (300, 0, 950, 50), exact=True)
            s = self.ui.capture()
            item = s.find("全部收取", (700, 405, 955, 475), exact=True)
            if not s.blue_button(item):
                continue
            self.ui.click(item)
            def dismiss(frame):
                item = frame.find("关闭|确认|确定", (250, 350, 750, 525), exact=True)
                if item:
                    self.ui.click(item)
            self.ui.wait(lambda s: s.find("活动任务", (0, 0, 280, 65))
                         and not s.blue_button(s.find("全部收取", (700, 405, 955, 475))),
                         "领取活动任务", handle=dismiss)
        self.home()
        self.log("已检查四类活动任务奖励")

    def memoirs(self):
        """This event's optional side stories; other mini-games stay untouched."""
        s = self.home()
        entry = s.find("回忆录", (0, 220, 170, 355))
        if not entry:
            return
        if not s.notification((78, 253, 120, 301)):
            self.log("回忆录入口无未领取提示，跳过")
            return
        self.ui.click(entry)
        idle = 0
        previous = None
        opened = 0
        for _ in range(360):
            self.check_deadline()
            s = self.ui.capture()
            if self.story_dialog(s):
                idle = 0
                continue
            if s.find("复制世界回忆录", (0, 0, 350, 70)):
                if not s.find("艾拉的世界|诗夏的世界", (0, 420, 960, 520)):
                    time.sleep(.6)
                    continue
                new = s.find("新内容|NEW", (0, 55, 960, 140))
                if new:
                    self.ui.click((245 if new.center[0] < 480 else 725, 235))
                    idle = 0
                elif s.find(r"[×xX].*30", (855, 0, 960, 65)):
                    # The epilogue advertises its unclaimed gem reward instead
                    # of showing the two world buttons' NEW marker.
                    self.ui.click((893, 30))
                    opened += 1
                else:
                    self.ui.save("memoirs_checked", s)
                    self.home()
                    self.log(f"回忆录本轮打开 {opened} 篇剧情")
                    return
            elif s.find("艾拉的世界|诗夏的世界", (0, 0, 320, 65)):
                new = s.find("新内容|NEW", (280, 35, 930, 510))
                if new:
                    vertical = s.find("诗夏的世界", (0, 0, 320, 65))
                    self.ui.click((new.center[0] if vertical else new.center[0]+90, new.center[1]+50 if vertical else new.center[1]+28))
                    opened += 1
                    idle = 0
                    previous = None
                else:
                    text = s.text((280, 60, 930, 520))
                    idle = idle+1 if text == previous else 0
                    previous = text
                    if idle >= 2:
                        self.ui.click((32, 30))
                        idle = 0
                    else:
                        self.ui.swipe((850, 435), (850, 185))
            else:
                time.sleep(.6)
        raise EventUIError("回忆录达到步骤上限，已保存当前进度")

    def sweep(self, hard=True):
        if hard:
            from .event_sweep import HardSweep
            return HardSweep(self).run()
        return self.sweep_normal()

    def sweep_normal(self):
        """Optional normal-stage sweeps using the player's remaining stamina."""
        kind, cost = "N", 10
        finished = set()
        for batch in range(30):
            self.check_deadline()
            self.quests()
            self.ui.expect_click("扫荡", (790, 95, 940, 150), exact=True)
            s = self.ui.wait(lambda s: s.find("关卡一览", (300, 0, 700, 70)), "系统扫荡")
            clear = s.find("解除所有勾选", (740, 75, 920, 140), exact=True)
            if clear:
                self.ui.click(clear)
            elif not s.find("全部勾选|勾选全部", (740, 75, 920, 140)):
                raise EventUIError("无法确认扫荡列表已解除之前的选项")
            selected = None
            for page in range(10):
                # Clearing an already empty selection emits a toast over H-2's
                # remaining-attempts field. Wait for it, never OCR through it.
                s = self.ui.wait(lambda s: s.find("关卡一览", (300, 0, 700, 70))
                                 and not s.find("未勾选任何关卡|正在进行数据连接"), "扫荡列表稳定")
                for row in s.all(rf"活动关卡{kind}-\d+", (35, 135, 350, 375)):
                    name = normalized(row.text)
                    if name in finished:
                        continue
                    y = row.center[1]
                    attempts = s.find(r"\d+/\d+", (435, y, 495, min(y+48, 378)))
                    remaining = int(normalized(attempts.text).split("/")[0]) if attempts else None
                    if remaining == 0:
                        finished.add(name)
                        continue
                    selected = (name, y, remaining)
                    break
                if selected:
                    break
                self.ui.swipe((700, 340), (700, 150))
            if not selected:
                self.ui.expect_click("取消", (460, 440, 710, 520), exact=True)
                self.log("未找到可扫荡普通关卡")
                return
            # Stamina is optional batching information, never a prerequisite.
            # If its digits are missing, request one sweep and let the game
            # decide affordability. Do not spend time retrying stamina OCR.
            stamina = s.number((270, 386, 335, 416))
            count = min(99, stamina // cost) if stamina is not None else 1
            if count < 1:
                self.ui.expect_click("取消", (460, 440, 710, 520), exact=True)
                self.report["pending"].append("体力不足，尚有普通关卡可扫荡")
                return
            self.ui.click((851, selected[1]+16))
            for _ in range(100):
                s = self.ui.capture()
                current = self.ui.number(s, (775, 395, 840, 436))
                if current is None:
                    raise EventUIError("扫荡次数无法识别")
                if current == count:
                    break
                self.ui.click((885 if current < count else 733, 413), delay=.1)
            else:
                raise EventUIError("设置扫荡次数超出上限")
            s = self.ui.capture()
            if s.find("体力不足", (35, 440, 470, 500)):
                self.ui.expect_click("取消", (460, 440, 710, 520), exact=True)
                self.report["pending"].append("系统扫荡体力不足；未购买体力")
                return
            button = s.find("一键扫荡", (700, 440, 920, 520), exact=True)
            if button is None or not s.blue_button(button):
                self.ui.expect_click("取消", (460, 440, 710, 520), exact=True)
                self.report["pending"].append("扫荡按钮不可用，停止扫荡并继续活动领奖")
                return
            self.ui.save(f"sweep_{batch:02d}_plan", s)
            self.ui.click(button)
            if self.settle_sweep(selected[0], count, cost, selected[2], stamina) is False:
                return
            self.log(f"系统扫荡 {selected[0]} × {count}")
        raise EventUIError("扫荡批次数达到上限")

    def settle_sweep(self, expected_name, expected_count, cost, remaining_before=None, stamina_before=None):
        seen_result = False
        confirmed = False
        for _ in range(35):
            s = self.ui.capture()
            self.ui.save("sweep_transition", s)
            if s.find("正在.*连接|数据连接|加载中|下载中", (0, 0, 960, 100)):
                # The confirmation closes before the server updates counters.
                # This dimmed bulk list is not the final settlement state.
                time.sleep(.6)
                continue
            if s.find("体力回复|体力恢复|购买体力"):
                item = s.find("取消", (200, 300, 800, 520), exact=True)
                if item:
                    self.ui.click(item)
                raise EventUIError("扫荡意外请求补充体力，已取消")
            if s.event_quests and seen_result:
                return
            if (confirmed or seen_result) and s.find("关卡一览", (300, 0, 700, 70)):
                row = s.find(re.escape(expected_name), (35, 135, 350, 375), exact=True)
                left = s.find(r"\d+/\d+", (435, row.center[1], 495, row.center[1]+48)) if row else None
                remaining = int(normalized(left.text).split("/")[0]) if left else None
                stamina = s.number((270, 386, 335, 416))
                verified = (remaining_before is not None and remaining == remaining_before-expected_count)
                if remaining_before is None:
                    verified = seen_result or (stamina_before is not None and stamina is not None
                                               and 0 <= stamina-(stamina_before-expected_count*cost) <= 1)
                    if not verified:
                        self.report["pending"].append("普通扫荡结算未能核实，停止追加扫荡并继续活动领奖")
                        self.ui.click(s.find("取消", (460, 440, 710, 520), exact=True))
                        self.ui.wait(lambda s: s.event_quests, "停止普通扫荡")
                        return False
                if not verified:
                    raise EventUIError("扫荡后次数/体力变化未能核实，停止重复消耗")
                self.ui.click(s.find("取消", (460, 440, 710, 520), exact=True))
                self.ui.wait(lambda s: s.event_quests, "扫荡完成返回关卡")
                return
            if s.find("一?键扫荡确认", (250, 0, 710, 70)):
                if confirmed:
                    time.sleep(.5)
                    continue
                rows = s.all(r"活动关卡[HN]-\d+", (35, 90, 360, 330))
                spend = s.number((225, 340, 265, 375))
                if (len(rows) != 1 or normalized(rows[0].text) != expected_name
                        or spend != expected_count*cost):
                    raise EventUIError("最终扫荡确认与计划不一致，未确认消耗")
                item = s.find("挑战", (460, 445, 720, 520), exact=True)
                confirmed = item is not None
            elif s.find("扫荡确认|使用扫荡券|消耗扫荡券|进行扫荡"):
                item = s.find("确认|确定|OK", (450, 300, 920, 525), exact=True)
            elif s.find("扫荡结果|获得道具|获得报酬|扫荡完成|扫荡券使用结果"):
                seen_result = True
                item = s.find("全部跳过|跳过|确认|确定|关闭|OK", (200, 300, 950, 535), exact=True)
            elif s.find("限定商店|限时商店"):
                item = s.find("取消|关闭", (200, 300, 800, 525), exact=True)
            else:
                item = None
            if item:
                self.ui.click(item)
            else:
                time.sleep(.7)
        raise EventUIError("系统扫荡结果未确认，停止重复消耗并保存截图")

    def exchange(self):
        s = self.home()
        if s.number((260, 340, 315, 377)) == 0:
            self.log("活动首页券余额为 0，跳过兑换")
            return
        self.ui.click(s.find("报酬[交兑]换", (180, 300, 350, 460)))
        self.ui.wait(lambda s: s.find("报酬[交兑]换", (0, 0, 300, 65)), "活动兑换")
        before = None
        total = 0
        for _ in range(80):
            self.check_deadline()
            s = self.ui.capture()
            if s.find("一键交换完毕|交换结果|获得报酬", (200, 100, 780, 250)):
                self.ui.expect_click("确认|确定|关闭", (250, 300, 730, 480), exact=True)
                continue
            if s.find("报酬[交兑]换", (0, 0, 300, 65)) and s.find("奖励券", (710, 420, 940, 470)):
                current = self.ui.number(s, (855, 423, 945, 465))
                if current is None:
                    raise EventUIError("活动奖励券余额无法确认")
                if before is not None:
                    if current >= before:
                        raise EventUIError("一键兑换后券数未减少，停止重复点击")
                    total += before-current
                if current == 0:
                    self.ui.save("exchange_empty", s)
                    self.log(f"本轮兑换 {total} 张活动奖励券，余额已确认 0")
                    self.home()
                    return
                button = s.find("一键交换", (710, 325, 940, 390), exact=True)
                consume = s.find(r"消耗\d+张", (710, 385, 940, 420))
                if not button or not consume or int(re.search(r"\d+", consume.text)[0]) != current:
                    raise EventUIError("一键兑换消耗与活动券余额不一致")
                before = current
                self.ui.save("exchange_plan", s)
                self.ui.click(button, delay=1.5)
            elif s.find("报酬[交兑]换", (0, 0, 300, 65)):
                item = s.find("确认|确定|关闭", (250, 350, 730, 480), exact=True)
                if item:
                    self.ui.click(item)
                else:
                    time.sleep(.5)
            else:
                time.sleep(.5)
        raise EventUIError("活动券兑换达到步骤上限")

    def run(self, hard_chapter=True, exhaust_power=False):
        try:
            if not self.enter():
                self.report["status"] = "unavailable"
                return self.report
            if self.options.get("first_clear", False) or self.options.get("bosses", False):
                from .event_battle import EventBattles
                battles = EventBattles(self)
            if self.options.get("first_clear", False):
                battles.first_clear()
            if self.options.get("bosses", False):
                battles.bosses()
            if hard_chapter:
                self.sweep()
            if exhaust_power:
                self.sweep(hard=False)
            if self.options.get("stories", True):
                self.stories()
            if self.options.get("memoirs", True):
                self.memoirs()
            if self.options.get("missions", True):
                self.missions()
            if self.options.get("exchange", True):
                self.exchange()
            self.report["status"] = "complete" if not self.report["pending"] else "partial"
            return self.report
        except Exception as error:
            self.report["status"] = "error"
            self.report["pending"].append(str(error))
            self.ui.save("error")
            raise
        finally:
            (self.ui.output / "report.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")
