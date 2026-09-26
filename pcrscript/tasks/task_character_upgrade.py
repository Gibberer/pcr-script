"""On-demand bulk character levelling and normal equipment upgrades."""
from __future__ import annotations

import json
import re
import cv2 as cv
import numpy as np

from .base import BaseTask, TaskOptions, TaskReport
from .registry import register
from ..game_ui.screen import EventUI, EventUIError, normalized
from ..run_session import clock as time


def selected_count(screen) -> int | None:
    item = screen.find(r'(?:选择角色)?\d+/20', (760, 60, 935, 90), exact=True)
    return int(re.search(r'(\d+)/20', normalized(item.text))[1]) if item else None


def checkbox_checked(image, point) -> bool:
    x, y = point
    hsv = cv.cvtColor(image[y-18:y+18, x-18:x+18], cv.COLOR_BGR2HSV)
    return float(np.mean((hsv[:, :, 0] > 90) & (hsv[:, :, 0] < 120)
                         & (hsv[:, :, 1] > 110) & (hsv[:, :, 2] > 160))) > .12


@register('upgrade_all_characters')
class UpgradeAllCharacters(BaseTask):
    config_section = 'CharacterUpgrade'

    def __init__(self, robot, options: TaskOptions | None = None) -> None:
        super().__init__(robot)
        self.options = self.task_options() if options is None else dict(options)
        self.ui = EventUI(robot.driver, self.options.get('output', 'cache/daily/character_upgrade'))
        self.report: TaskReport = dict(status='running', history=[], pending=[])
        self.deadline = time.monotonic() + self.options.get('timeout', 1800)

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise EventUIError('角色强化任务超时')

    def save_report(self) -> None:
        (self.ui.output/'report.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')

    def bulk(self):
        return self.ui.wait(lambda s: s.find('一键强化', (300, 20, 670, 60), exact=True)
                            and selected_count(s) is not None
                            and not s.find('正在进行数据连接'), '一键强化选择页')

    def enter(self) -> bool:
        for _ in range(12):
            self.check()
            s = self.ui.capture()
            if (s.find('角色一览', (30, 0, 250, 60))
                    and s.find('没有可一键强化的角色[。.]?', (240, 240, 720, 300), exact=True)):
                self.ui.save('already_maxed', s)
                return False
            if s.find('一键强化', (300, 20, 670, 60), exact=True):
                self.bulk()
                return True
            if s.find('角色一览', (30, 0, 250, 60)):
                self.ui.click((872, 419))
            elif button := s.find('角色', (130, 480, 250, 540), exact=True):
                self.ui.click(button, delay=1.5)
            else:
                time.sleep(1)
        raise EventUIError('未能从已知页面进入角色一键强化')

    def enable_checks(self, points) -> None:
        for point in points:
            s = self.ui.capture()
            if not checkbox_checked(s.image, point):
                self.ui.click(point)
                if not checkbox_checked(self.ui.capture().image, point):
                    raise EventUIError('强化条件勾选状态无法确认')

    def configure(self, mode: str) -> None:
        self.bulk()
        self.ui.expect_click('解除全选', (650, 90, 770, 130), exact=True)
        self.ui.click((65, 110))  # All elements; never inherit a previous filter.
        self.ui.click((98, 421 if mode == 'rank' else 384))
        self.ui.expect_click('变更', (175, 390, 290, 440), exact=True)
        title = '品级提升条件设定' if mode == 'rank' else '自动强化条件设定'
        s = self.ui.wait(lambda s: s.find(title, (270, 20, 700, 60), exact=True), title)
        if mode == 'rank':
            if not s.find('降序', (590, 90, 695, 130), exact=True):
                raise EventUIError('品级列表不是已确认的降序布局')
            for _ in range(3):
                self.ui.swipe((480, 200), (480, 365))
            s = self.ui.capture()
            item = s.find(r'品级\d+', (350, 135, 610, 180), exact=True)
            if not item:
                raise EventUIError('最高可用品级未知')
            self.report['target_rank'] = int(re.search(r'\d+', item.text)[0])
            self.ui.click(item)
            self.enable_checks([(422, 423)])
        else:
            for label in ('角色等级和技能等级强化', '佩戴装备至未装备槽', '最大限度强化装备'):
                if not s.find(label, (300, 100, 670, 290), exact=True):
                    raise EventUIError('自动强化条件布局未知')
            self.enable_checks([(291, 136), (291, 202), (547, 202), (291, 268)])
        self.ui.save('conditions_'+mode)
        self.ui.expect_click('确认', (480, 450, 710, 510), exact=True)
        self.bulk()

    def batches(self, mode: str) -> None:
        for batch in range(self.options.get('max_batches', 40)):
            self.check()
            self.report_progress(f"{'品级提升' if mode == 'rank' else '自动强化'} · 第 {batch + 1} 批")
            self.bulk()
            self.ui.expect_click('自动选择', (770, 90, 930, 130), exact=True)
            s = self.bulk()
            count = selected_count(s)
            self.ui.save(f'{mode}_{batch:02d}_selected', s)
            if s.find('不足|无法强化'):
                raise EventUIError('资源不足或角色无法强化，保留现场')
            if count == 0:
                # A second automatic selection must agree, with confirmation disabled.
                self.ui.click(s.find('自动选择', (770, 90, 930, 130), exact=True))
                s = self.bulk()
                if selected_count(s) != 0 or s.blue_button(s.find('确认', (480, 450, 710, 510), exact=True)):
                    raise EventUIError('空选择与确认按钮状态不一致')
                self.report[mode+'_exhausted'] = True
                return
            if count is None or not 1 <= count <= 20:
                raise EventUIError('本批角色数量无法确认')
            button = s.find('确认', (480, 450, 710, 510), exact=True)
            if not s.blue_button(button):
                raise EventUIError('本批强化不可执行')
            self.ui.click(button)
            phrase = '品级提升' if mode == 'rank' else '自动强化'
            s = self.ui.wait(lambda s: s.find('一?键'+phrase+'确认', (270, 20, 700, 60), exact=True), '批量强化确认')
            self.ui.save(f'{mode}_{batch:02d}_confirm', s)
            self.ui.expect_click('确认', (480, 450, 710, 510), exact=True)
            s = self.ui.wait(lambda s: s.find('一?键'+phrase+'完成', (270, 20, 700, 60), exact=True), '批量强化完成', timeout=90)
            self.ui.save(f'{mode}_{batch:02d}_done', s)
            self.report['history'].append(dict(mode=mode, count=count, result=s.text()))
            self.save_report()
            print(f'[角色强化] {mode} 第{batch+1}批完成，{count}名', flush=True)
            self.ui.expect_click('确认', (350, 450, 610, 510), exact=True)
        raise EventUIError('达到批次上限，未宣称全部完成')

    def run(self) -> TaskReport:
        try:
            self.report_progress('进入角色强化页面')
            if not self.enter():
                self.report['status'] = 'already_complete'
                self.report['reason'] = '游戏明确提示没有可一键强化的角色'
                return self.report
            for mode in ('rank', 'auto'):
                self.configure(mode)
                self.batches(mode)
            self.report['status'] = 'complete'
            self.ui.expect_click('取消', (265, 450, 475, 510), exact=True)
            self.ui.wait(lambda s: s.find('角色一览', (30, 0, 250, 60)), '返回角色一览')
        except EventUIError as error:
            self.report['status'] = 'partial'
            self.report['pending'].append(str(error))
            self.ui.save('stopped')
        finally:
            self.save_report()
        return self.report
