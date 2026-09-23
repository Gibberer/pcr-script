"""Raise owned characters' bond with held gifts and read unlocked character stories."""
from __future__ import annotations

import json
import re
from pathlib import Path

import cv2 as cv
import numpy as np

from .base import BaseTask, TaskOptions, TaskReport
from .registry import register
from ..game_ui.screen import EventUI, EventUIError, normalized
from ..run_session import clock as time


def gift_grades(screen) -> tuple[int, int] | None:
    left = screen.find(r'品级\d+', (290, 205, 410, 245), exact=True)
    right = screen.find(r'品级\d+', (475, 200, 615, 245), exact=True)
    if not left or not right:
        return None
    return (int(re.search(r'\d+', normalized(left.text))[0]),
            int(re.search(r'\d+', normalized(right.text))[0]))


def gift_counts(screen) -> list[int]:
    result = []
    for item in screen.all(r'[×xX]\d+', (340, 325, 680, 390)):
        match = re.search(r'[×xX](\d+)', normalized(item.text))
        if match:
            result.append(int(match[1]))
    return result


def verified_gift_counts(ui: EventUI, screen) -> list[int]:
    """Read every visible gift stack, including small counts missed by full-frame OCR."""
    counts = []
    for x in (390, 460, 530, 600):
        patch = screen.image[326:367, x-27:x+27]
        hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
        occupied = float(np.mean(hsv[:, :, 1] > 70)) > .18
        if not occupied:
            continue
        items = screen.all(r'[×xX]\d+', (x-9, 360, x+42, 395))
        if not items:
            items = ui.read_region(screen, (x-1, 362, x+41, 388)).items
        parsed = [int(match[1]) for item in items if item.score >= .80
                  if (match := re.search(r'[×xX](\d+)', normalized(item.text)))]
        if len(parsed) != 1:
            return []
        counts.append(parsed[0])
    return counts


def card_present(screen, x: int, y: int) -> bool:
    patch = screen.image[y-36:y+36, x-60:x+60]
    hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
    return float(np.mean(hsv[:, :, 1] > 45)) > .17


@register('max_character_bonds', requires_home=True)
class MaxCharacterBonds(BaseTask):
    """Use existing gifts only; every spend and first-read reward is recorded."""

    config_section = 'CharacterBond'

    def __init__(self, robot, options: TaskOptions | None = None) -> None:
        super().__init__(robot)
        self.options = self.task_options() if options is None else dict(options)
        self.ui = EventUI(robot.driver, self.options.get('output', 'cache/daily/character_bond'))
        self.report: TaskReport = dict(status='running', characters=[], pending=[], gifts_spent=[], stories_read=[])
        self.deadline = time.monotonic() + self.options.get('timeout', 21600)
        self.attempted: set[str] = set()

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise EventUIError('好感度任务超时，已保存接续记录')

    def save(self) -> None:
        path = self.ui.output/'report.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)

    def roster(self):
        return self.ui.wait(lambda s: s.find('角色一览', (25, 0, 250, 65)), '角色一览')

    def enter(self) -> None:
        s = self.ui.capture()
        if not s.find('角色一览', (25, 0, 250, 65)):
            self.ui.wait(lambda s: s.find('角色', (145, 480, 260, 540), exact=True), '角色入口')
            self.ui.click((195, 505))
        self.roster()
        self.ui.click((670, 28))
        s = self.ui.wait(lambda s: s.find('分类', (350, 15, 610, 75), exact=True), '角色排序')
        for pattern, roi in [('从低到高', (240, 100, 400, 165)), ('好感度', (245, 310, 400, 380))]:
            item = s.find(pattern, roi, exact=True)
            if not item:
                raise EventUIError('角色好感度升序选项未知')
            self.ui.click(item, delay=.3)
            s = self.ui.capture()
        self.ui.expect_click('确认', (470, 450, 705, 515), exact=True)
        s = self.roster()
        if not s.find('好感度', (620, 0, 740, 55), exact=True):
            raise EventUIError('角色列表未按好感度排序')

    def detail(self):
        return self.ui.wait(lambda s: s.find('角色强化', (40, 0, 250, 65))
                            and s.find('好感度剧情', (0, 315, 100, 385)), '角色详情')

    def story_list(self):
        return self.ui.wait(lambda s: s.find('角色剧情', (320, 15, 620, 70), exact=True), '角色剧情')

    def gift_dialog(self):
        return self.ui.wait(lambda s: s.find('赠礼', (380, 15, 580, 70), exact=True)
                            and s.find('消耗礼物后的好感度', (250, 230, 550, 285)), '赠礼预览')

    def give_gifts(self, record: dict) -> None:
        self.story_list()
        self.ui.expect_click('好感度提升', (475, 450, 710, 515), exact=True)
        s = self.gift_dialog()
        name = normalized(s.text((260, 90, 450, 120)))
        if not name:
            raise EventUIError('赠礼角色身份未读出')
        if self.options.get('focus_character') and name != normalized(self.options['focus_character']):
            raise EventUIError('赠礼衣装与指定角色不一致，未送出礼物')
        record['name'] = name
        if name in self.attempted:
            record['status'] = 'already_checked_this_run'
            self.ui.expect_click('取消', (255, 450, 475, 515), exact=True)
            return
        self.attempted.add(name)
        self.ui.save('gift_before_'+name, s)
        self.ui.expect_click('最大强化', (605, 190, 705, 250), exact=True)
        s = self.gift_dialog()
        levels = gift_grades(s)
        if not levels:
            raise EventUIError('赠礼前后好感度品级无法确认')
        record.update(before=levels[0], target=levels[1], preview=str(self.ui.save('gift_max_'+name, s)))
        if s.find('已无法继续提高好感度'):
            record['bond'] = 'already_maxed'
            self.ui.expect_click('取消', (255, 450, 475, 515), exact=True)
            return
        counts = verified_gift_counts(self.ui, s)
        if not levels[0] < levels[1] <= 12 or not counts or sum(counts) > self.options.get('max_gifts_per_character', 2000):
            raise EventUIError('最大强化目标或礼物用量未通过核验')
        button = s.find('赠送', (470, 450, 710, 515), exact=True)
        if not s.blue_button(button) or s.find('不足|无法|不够'):
            record['bond'] = 'insufficient_gifts'
            self.report['pending'].append(name+'：现有礼物不足以达到预览目标')
            self.ui.expect_click('取消', (255, 450, 475, 515), exact=True)
            return
        spend = dict(name=name, before=levels[0], target=levels[1], counts=counts,
                     status='pending', evidence=record['preview'])
        self.report['gifts_spent'].append(spend)
        self.save()
        self.ui.click(button)
        s = self.ui.wait(lambda frame: frame.find('剧情解锁', (300, 15, 660, 70), exact=True)
                         or frame.find('角色剧情', (320, 15, 620, 70), exact=True), '赠礼结果', timeout=90)
        if s.find('剧情解锁', (300, 15, 660, 70), exact=True):
            spend['unlock_evidence'] = str(self.ui.save('bond_unlocked_'+name, s))
            self.ui.expect_click('关闭', (370, 450, 590, 515), exact=True)
            self.story_list()
        spend['status'] = 'confirmed'
        record['bond'] = 'raised'
        self.save()

    def read_stories(self, record: dict) -> None:
        if record.get('status') == 'already_checked_this_run':
            return
        name = record['name']
        max_steps = self.options.get('max_story_steps_per_character', 200)
        empty_pages = 0
        unknown_frames = 0
        scan_direction = 'to_top'
        previous = None
        for step in range(max_steps):
            self.check()
            s = self.ui.capture()
            recognized = True
            if s.find('剧情解锁', (300, 15, 660, 70), exact=True):
                self.ui.expect_click('关闭', (370, 450, 590, 515), exact=True)
            elif s.find('报酬确认', (300, 15, 660, 125), exact=True):
                receipt = dict(name=name, reward=s.text(), evidence=str(self.ui.save('story_reward_'+name+'_'+str(step), s)))
                self.report['stories_read'].append(receipt)
                self.save()
                self.ui.expect_click('关闭', (370, 395, 590, 515), exact=True)
            elif s.find('剧情梗概', (300, 100, 650, 180), exact=True):
                self.ui.expect_click('跳过', (470, 345, 710, 410), exact=True)
            elif s.find('剧情阅读确认', (300, 55, 660, 125), exact=True) or s.find('数据下载', (300, 110, 660, 175), exact=True):
                button = s.find('无语音', (390, 330, 565, 465))
                if not button:
                    raise EventUIError('剧情无语音下载按钮未知')
                self.ui.click(button, delay=1.5)
            elif s.find('跳过', (825, 95, 950, 160), exact=True):
                self.ui.expect_click('跳过', (825, 95, 950, 160), exact=True)
            elif s.find('菜单', (855, 0, 950, 90), exact=True):
                self.ui.click((917, 42), delay=.2)
            elif s.find('角色剧情', (320, 15, 620, 70), exact=True):
                new = s.find('新内容', (245, 110, 715, 435))
                if new:
                    record['stories_opened'] = record.get('stories_opened', 0)+1
                    self.ui.save('story_new_'+name+'_'+str(record['stories_opened']), s)
                    self.ui.click((480, min(new.center[1]+38, 415)))
                    empty_pages = 0
                    scan_direction = 'to_top'
                    previous = None
                else:
                    crop = cv.resize(s.image[125:430, 300:680], (38, 31), interpolation=cv.INTER_AREA)
                    if previous is not None and float(np.mean(np.abs(crop.astype(int)-previous.astype(int)))) < 1.5:
                        if scan_direction == 'to_top':
                            scan_direction = 'to_bottom'
                            previous = None
                            continue
                        record['stories'] = 'checked_to_end'
                        return
                    previous = crop
                    empty_pages += 1
                    if empty_pages >= 30:
                        raise EventUIError('角色剧情列表未找到底部，保留未完成状态')
                    if scan_direction == 'to_top':
                        self.ui.swipe((590, 170), (590, 375))
                    else:
                        self.ui.swipe((590, 375), (590, 170))
            elif s.find('正在进行数据连接|加载中'):
                time.sleep(1)
            else:
                recognized = False
                unknown_frames += 1
                if unknown_frames >= 10:
                    raise EventUIError('角色剧情出现持续未知页面')
                time.sleep(1)
            if recognized:
                unknown_frames = 0
        raise EventUIError('角色剧情步骤达到上限，保留未完成状态')

    def return_to_roster(self) -> None:
        s = self.ui.capture()
        if s.find('角色剧情', (320, 15, 620, 70), exact=True):
            self.ui.expect_click('关闭', (255, 450, 475, 515), exact=True)
        self.detail()
        self.ui.click((35, 32))
        self.roster()

    def process_detail(self) -> str | None:
        self.detail()
        self.ui.expect_click('好感度剧情', (0, 315, 100, 385))
        self.story_list()
        record = dict(status='checking')
        self.report['characters'].append(record)
        self.save()
        self.give_gifts(record)
        self.read_stories(record)
        if record.get('status') != 'already_checked_this_run':
            record['status'] = 'complete' if record.get('stories') == 'checked_to_end' and record.get('bond') != 'insufficient_gifts' else 'partial'
        self.save()
        self.return_to_roster()
        return record.get('name')

    def process_card(self, x: int, y: int) -> str | None:
        self.ui.click((x, y))
        return self.process_detail()

    def run(self) -> TaskReport:
        try:
            self.enter()
            if focus := self.options.get('focus_character'):
                from ..game_ui.character_equipment import open_character_memory
                if open_character_memory(self.ui, focus) is None:
                    raise EventUIError('指定角色的完整衣装身份未能确认')
                self.process_detail()
                self.report['status'] = 'complete' if self.report['characters'][-1].get('status') == 'complete' else 'partial'
                return self.report
            slots = [(x, y) for y in (149, 294, 420) for x in (165, 472, 770)]
            max_characters = self.options.get('max_characters', 400)
            max_pages = self.options.get('max_pages', 80)
            scanned = 0
            for page in range(max_pages):
                self.check()
                for x, y in slots:
                    self.check()
                    s = self.roster()
                    if not card_present(s, x, y):
                        continue
                    if len(self.attempted) >= max_characters:
                        self.report['status'] = 'partial'
                        self.report['pending'].append('达到本轮角色数量上限，下一次可接续')
                        return self.report
                    # A raised character moves towards the end of the ascending
                    # list. Re-check this slot once for the character shifted in.
                    for _ in range(max_characters+1):
                        name = self.process_card(x, y)
                        scanned += 1
                        if len(self.attempted) >= max_characters:
                            self.report['status'] = 'partial'
                            self.report['pending'].append('达到本轮角色数量上限，下一次可接续')
                            self.report['scanned_cards'] = scanned
                            return self.report
                        if name in self.attempted and self.report['characters'][-1].get('status') == 'already_checked_this_run':
                            break
                    else:
                        raise EventUIError('角色升序列表没有收敛，停止重复操作')
                before = self.roster().image.copy()
                self.ui.swipe((875, 415), (875, 150))
                after = self.roster().image
                delta = float(np.mean(np.abs(before[110:180, 100:250].astype(int)
                                             - after[110:180, 100:250].astype(int))))
                if delta < 1.5:
                    self.report['status'] = 'complete' if all(r.get('status') in ('complete','already_checked_this_run') for r in self.report['characters']) else 'partial'
                    self.report['scanned_cards'] = scanned
                    return self.report
            self.report['status'] = 'partial'
            self.report['pending'].append('达到角色列表翻页上限，未宣称全部处理')
        except EventUIError as error:
            self.report['status'] = 'partial'
            self.report['pending'].append(str(error))
            if self.report['characters'] and self.report['characters'][-1].get('status') == 'checking':
                self.report['characters'][-1]['status'] = 'partial'
                self.report['characters'][-1]['reason'] = str(error)
            self.ui.save('stopped')
        finally:
            self.save()
        return self.report
