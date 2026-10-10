from .image import ImageTask
from typing import TYPE_CHECKING

from ..constants import *
from pcrscript.actions import *
from ..templates import ImageTemplate
from ..game_ui.screen import EventUI, EventUIError, normalized
from ..run_session import clock as time

if TYPE_CHECKING:
    from pcrscript import Robot

from .registry import register
from ._actions import _clean_oneshot_actions

@register("arena", requires_home=True)
class Arena(ImageTask):
    '''
    竞技场
    '''

    def run(self):
        self.action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(3),
            ClickAction(pos=(550, 411)),
            SleepAction(1),
            MatchAction(template='btn_cancel', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=2),
            ClickAction(pos=(295, 336)),
            MatchAction(template='btn_ok', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=2),
            ClickAction(pos=(665, 186)),
            SleepAction(3),
            ClickAction(pos=(849, 454)),
            SleepAction(2),
            MatchAction(template='btn_arena_skip', matched_actions=[ClickAction()], timeout=8),
            MatchAction(['btn_next_step_small', 'btn_next_step'], matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
        )


@register("princess_arena", requires_home=True)
class PrincessArena(ImageTask):
    '''
    公主竞技场
    '''

    def run(self):
        self.action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(3),
            ClickAction(pos=(705, 411)),
            SleepAction(1),
            MatchAction(template='btn_cancel', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=2),
            ClickAction(pos=(295, 336)),
            MatchAction(template='btn_ok', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=2),
            ClickAction(pos=(665, 186)),
            SleepAction(3),
            ClickAction(pos=(849, 454)),
            SleepAction(1),
            ClickAction(pos=(849, 454)),
            SleepAction(1),
            ClickAction(pos=(849, 454)),
            SleepAction(2),
            MatchAction(template='btn_arena_skip', matched_actions=[ClickAction()], timeout=20),
            MatchAction(['btn_next_step_small', 'btn_next_step'], matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
        )


@register("research", requires_home=True)
class Research(ImageTask):
    '''
    圣迹调查
    '''

    def run(self):
        actions = [
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(2),
            ClickAction(pos=(740, 150)),
            MatchAction('symbol_research', matched_actions=[
                ClickAction(offset=(100, 200))], timeout=5),
        ]
        # 圣迹2级
        actions += [
            ClickAction(pos=(587, 300)),
            SleepAction(2),
            ClickAction(pos=(718, 146)),
            *_clean_oneshot_actions(),
            SleepAction(1),
            ClickAction(pos=(37, 33)),
            SleepAction(1)
        ]
        # 神殿2级
        actions += [
            ClickAction(pos=(800, 300)),
            SleepAction(2),
            ClickAction(pos=(718, 146)),
            *_clean_oneshot_actions(),
            SleepAction(1)
        ]
        self.action_squential(*actions)


@register("schedule", requires_home=True)
class Schedule(ImageTask):
    """Run the saved schedule and verify its own completion counter."""

    def __init__(self, robot):
        super().__init__(robot)
        self.ui = EventUI(robot.driver, getattr(robot, '_task_output', None) or 'cache/daily/schedule')

    @staticmethod
    def book(screen):
        if screen.find('正在进行数据连接|连接中|加载中'):
            return False
        controls = [screen.find(text, roi, exact=True) for text, roi in (
            ('关闭', (195, 450, 355, 515)),
            ('列表设定', (370, 450, 545, 515)),
            ('一键自动', (555, 450, 765, 515)),
        )]
        # Auto becomes disabled when the whole schedule is done. The two
        # white footer controls distinguish the book from its dimmed backdrop.
        return (all(item and item.score >= .95 for item in controls)
                and float(screen.image[452:508, 205:535].mean()) > 180)

    def completion(self, screen):
        heading = screen.find('交给可可萝', (350, 90, 600, 435), exact=True)
        if heading is None or heading.score < .95:
            return None
        y = heading.center[1]
        roi = (710, y-18, 770, y+18)
        # Full-frame orientation classification can rotate 9/9 into 6/6.
        # This field is upright; reread it without classification every time.
        value = self.ui.read_region(screen, roi, classify=False).find(r'\d+/\d+', roi, exact=True)
        if value is None or value.score < .95:
            return None
        done, total = map(int, normalized(value.text).split('/'))
        return (done, total) if 0 <= done <= total <= 99 else None

    @staticmethod
    def remaining(screen):
        heading = screen.find('交给可可萝', (350, 90, 600, 435), exact=True)
        top = heading.center[1] if heading else 90
        rows = []
        for button in screen.all('执行', (685, top, 765, 440)):
            if button.score < .95 or not screen.blue_button(button):
                continue
            y = button.center[1]
            labels = screen.all('.+', (195, max(top, y-30), 680, min(440, y+35)))
            rows.append(' '.join(item.text for item in sorted(labels, key=lambda item: item.center[1])
                                 if item.score >= .95))
        return rows

    def restore_counter(self, screen):
        for _ in range(4):
            if not self.book(screen) or self.completion(screen) is not None:
                return screen
            roi = (769, 97, 784, 445)
            if self.ui.scrollbar_bounds(screen, roi) is None or not self.ui.scrollbar(
                    screen, roi, -1,
                    reached=lambda view: self.book(view) and self.completion(view) is not None):
                break
            screen = self.ui.capture()
        return screen

    def handle_result(self, screen):
        if self.book(screen):
            return
        if screen.find('回复体力|回复挑战次数|重置', (240, 110, 725, 425)):
            raise EventUIError('日程表出现资源回复或重置确认，未继续确认')
        if screen.find('持有上限', (240, 100, 725, 425)):
            self.warnings.add('日程执行中出现持有上限提示')
        roi = (350, 0, 960, 540)
        template = (ImageTemplate('btn_ok_blue', roi=roi) | ImageTemplate('btn_ok', threshold=.95, roi=roi)
                    | ImageTemplate('btn_skip_ok', roi=roi) | ImageTemplate('btn_close', threshold=.9, roi=roi))
        pos = self.template_match(screen.image, template)
        if pos:
            self.ui.click(pos)

    def finish_report(self, screen, status):
        value = self.completion(screen) if self.book(screen) else None
        rows = self.remaining(screen) if value else []
        report = dict(status=status, completed=value[0] if value else None,
                      total=value[1] if value else None, remaining_items=rows,
                      warnings=sorted(self.warnings), pending=[])
        if status == 'partial':
            report['pending'].append(f'日程表完成 {value[0]}/{value[1]}' if value else '日程表完成数未核实')
            if value and value[1] != self.expected_total:
                report['pending'].append('日程项目总数发生变化，未核实原计划是否完成')
            report['pending'].extend(rows)
            report['pending'].extend(report['warnings'])
        self.ui.save('schedule_result', screen)
        return report

    def run(self):
        self.warnings = set()
        entry = MatchAction(template="symbol_schedule", unmatch_actions=[
                ClickAction("icon_schedule"),
                ClickAction("btn_cancel")
            ], timeout=30)
        self.action_squential(entry)
        if entry.is_timeout:
            raise EventUIError('未能进入日程表')
        screen = self.ui.wait(self.book, '日程表页面')
        screen = self.restore_counter(screen)
        before = self.completion(screen)
        if before is None:
            raise EventUIError('日程表“交给可可萝”完成数未核实，未提交一键自动')
        self.expected_total = before[1]
        if before[0] == before[1]:
            report = self.finish_report(screen, 'already_complete')
            self.ui.click(screen.find('关闭', (195, 450, 355, 515), exact=True))
            return report
        start = screen.find('一键自动', (555, 450, 765, 515), exact=True)
        if not screen.blue_button(start):
            self.warnings.add('一键自动按钮不可用')
            return self.finish_report(screen, 'partial')
        self.ui.save('schedule_before', screen)
        self.ui.click(start)
        deadline = time.monotonic() + 180
        stable = 0
        while time.monotonic() < deadline:
            screen = self.ui.capture()
            screen = self.restore_counter(screen)
            value = self.completion(screen) if self.book(screen) else None
            self.report_progress(f'核对日程表 {value[0]}/{value[1]}' if value else '等待日程执行与结算')
            stable = stable + 1 if value and value[0] == value[1] and value[1] == before[1] else 0
            if stable >= 3:
                report = self.finish_report(screen, 'complete')
                self.ui.click(screen.find('关闭', (195, 450, 355, 515), exact=True))
                return report
            self.handle_result(screen)
            time.sleep(.3)
        return self.finish_report(screen, 'partial')
