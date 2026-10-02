"""Claim ordinary Recollection rewards and sweep already cleared dominions."""
from __future__ import annotations

from .registry import register
from .recollection_flow import RecollectionTask, RecollectionBlocked
from ..game_ui import recollection as field
from ..game_ui.screen import EventUIError
from ..run_session import RunCancelled, ResumeUnsafe


@register('recollection', requires_home=False)
class Recollection(RecollectionTask):
    config_section = 'Recollection'

    def collect_rewards(self):
        self.report_progress('领取普通追忆战报酬')
        s = self.detail(field.AREAS['memory'])
        if s is None:
            raise RecollectionBlocked('普通追忆战未解锁，未领取报酬')
        enabled = field.claim_enabled(s)
        if enabled is None:
            s = self.wait(lambda s: field.claim_enabled(s) is not None, '追忆战领取按钮状态', timeout=5)
            enabled = field.claim_enabled(s)
        if not enabled:
            pending = self.state.pop('pending_claim', None)
            self.report['rewards'] = 'recovered_claim' if pending else 'empty'
            if pending:
                self.report['history'].append(dict(pending, action='claim', outcome='recovered_claim',
                                                  after=str(self.ui.save('claim_recovered', s))))
            self.save()
            return
        if self.state.get('pending_claim'):
            raise RecollectionBlocked('上次追忆战领奖尚未核对，未重复领取')
        if self.options['preview_only']:
            self.report['rewards'] = 'available'
            return
        self.state['pending_claim'] = dict(evidence=str(self.ui.save('claim_before', s)))
        self.save()
        self.click(s, '领取', (580, 395, 685, 460))
        receipt = self.wait(field.receipt, '追忆战领奖回执')
        self.state['pending_claim']['receipt'] = str(self.ui.save('claim_receipt', receipt))
        self.save()
        self.click(receipt, '确认|关闭|确定', (250, 430, 720, 525))
        s = self.wait(lambda s: field.claim_enabled(s) is False, '追忆战宝箱清空')
        self.report['history'].append(dict(action='claim', **self.state['pending_claim'],
                                           after=str(self.ui.save('claim_after', s))))
        self.report['rewards'] = 'claimed'
        self.state.pop('pending_claim')
        self.save()

    def catalogue(self):
        s = self.index()
        if s is None:
            return None
        counts = field.index_attempts(s)
        self.ui.save('dominion_index_'+str(len(self.report['history'])), s)
        if not counts:
            raise RecollectionBlocked('领域剩余挑战次数无法确认')
        self.report['remaining_attempts'] = counts
        wanted = [field.AREAS[key] for key in self.options['areas']]
        locked = []
        for area in wanted:
            row = s.find(area, (100, 310, 850, 375), exact=True)
            if row is None:
                raise RecollectionBlocked('目标领域卡片无法核对：'+area)
            if field.card_locked(s, row):
                locked.append(area)
            elif area not in counts:
                raise RecollectionBlocked('目标领域的剩余次数未知：'+area)
        self.report['locked_areas'] = locked
        wanted = [area for area in wanted if area not in locked]
        if not any(counts.get(area, 0) for area in wanted):
            return None
        self.click(s, '一?键扫荡', (700, 400, 945, 470))
        s = self.wait(lambda s: field.bulk_catalogue(s) or s.find('没有可.*扫荡|无可.*扫荡'), '追忆战扫荡列表')
        if not field.bulk_catalogue(s):
            self.report['unsweepable'] = list(wanted)
            return None
        rows = field.sweep_rows(s)
        if rows is None:
            raise RecollectionBlocked('扫荡列表的领域、层数或剩余次数未知')
        if any(counts.get(row.area) != row.remaining for row in rows):
            raise RecollectionBlocked('领域列表与扫荡预览次数不一致')
        # The game catalogue includes only the highest cleared floor per domain.
        self.report['unsweepable'] = [area for area in wanted if area not in {r.area for r in rows} and counts.get(area, 0)]
        return s, rows

    def configure_sweep(self, screen, rows, budget):
        before = self.ui.number(screen, (230, 375, 335, 415))
        if before is None:
            raise RecollectionBlocked('扫荡券余额未知')
        wanted = [field.AREAS[key] for key in self.options['areas']]
        candidates = sorted((r for r in rows if r.area in wanted and r.remaining > 0),
                            key=lambda r: wanted.index(r.area))
        selected = candidates[:min(budget, before)]
        if not selected:
            raise RecollectionBlocked('没有可在预算内扫荡的领域或扫荡券不足')
        quantity = min(min(r.remaining for r in selected), budget//len(selected), before//len(selected))
        selected_areas = {r.area for r in selected}
        for row in rows:
            s = self.capture()
            fresh = field.sweep_rows(s)
            if fresh is None or {(r.area, r.floor, r.remaining) for r in fresh} != {(r.area, r.floor, r.remaining) for r in rows}:
                raise RecollectionBlocked('调整扫荡选项时目标发生变化')
            current = next(r for r in fresh if r.area == row.area)
            if current.selected != (row.area in selected_areas):
                self.ui.click((848, current.label.center[1]+14))
        for _ in range(100):
            s = self.capture()
            held = self.ui.number(s, (765, 355, 850, 398))
            if held is None or not 1 <= held <= 99:
                raise RecollectionBlocked('每关扫荡数量无法确认')
            if held == quantity:
                break
            self.ui.click((731 if held > quantity else 883, 375))
        else:
            raise RecollectionBlocked('扫荡数量调整达到上限')
        s = self.capture()
        configured = field.sweep_rows(s)
        cost = quantity*len(selected)
        after = self.ui.number(s, (365, 375, 455, 415))
        if (configured is None or {r.area for r in configured if r.selected} != selected_areas
                or self.ui.number(s, (230, 375, 335, 415)) != before
                or self.ui.number(s, (765, 355, 850, 398)) != quantity
                or after != before-cost or cost > budget):
            raise RecollectionBlocked('扫荡勾选、数量和券预览不一致')
        return s, dict(tickets_before=before, tickets_after=after, cost=cost, quantity=quantity,
                       targets=[dict(area=r.area, floor=r.floor, remaining=r.remaining) for r in selected])

    def verify_confirmation(self, s, plan):
        rows = field.sweep_rows(s)
        if (not field.bulk_confirmation(s) or rows is None
                or {(r.area, r.floor, r.remaining) for r in rows}
                   != {(r['area'], r['floor'], r['remaining']) for r in plan['targets']}):
            raise RecollectionBlocked('最终确认的扫荡领域或层数不符')
        for row in rows:
            y = row.label.center[1]
            if self.ui.number(s, (820, y+5, 925, y+43)) != plan['quantity']:
                raise RecollectionBlocked('最终确认的各领域扫荡次数不符')
        if (self.ui.number(s, (820, 365, 930, 410)) != plan['cost']
                or self.ui.number(s, (195, 370, 265, 415)) != plan['cost']
                or self.ui.number(s, (400, 370, 510, 415)) != plan['tickets_before']
                or not s.find(str(len(rows))+'处', (650, 350, 790, 410), exact=True)):
            raise RecollectionBlocked('最终确认的总次数或消耗券数不符')
        button = s.find('挑战', (480, 440, 710, 520), exact=True)
        if not s.blue_button(button):
            raise RecollectionBlocked('扫荡最终确认按钮不可用')

    def reconcile_sweep(self):
        plan = self.state['pending_sweep']
        s = self.index()
        counts = field.index_attempts(s) if s is not None else {}
        if any(counts.get(row['area']) != row['remaining']-plan['quantity'] for row in plan['targets']):
            raise RecollectionBlocked('待核对扫荡的挑战次数未按预览扣除；未重复扫荡')
        tag = str(len(self.report['history']))
        evidence = str(self.ui.save('sweep_attempts_after_'+tag, s))
        s = self.detail(plan['targets'][0]['area'])
        if s is None or self.ui.number(s, (525, 350, 598, 380)) != plan['tickets_after']:
            raise RecollectionBlocked('待核对扫荡的券余额不符；保留消费记录')
        record = dict(plan, action='sweep', attempts_after=counts, attempts_evidence=evidence,
                      tickets_evidence=str(self.ui.save('sweep_tickets_after_'+tag, s)))
        self.report['history'].append(record)
        self.report['spent'] = self.report.get('spent', 0)+plan['cost']
        self.report['remaining_attempts'] = counts
        self.state.pop('pending_sweep')
        self.save()

    def sweep(self):
        self.report_progress('扫荡已通关的追忆战·霸')
        if self.state.get('pending_sweep'):
            self.reconcile_sweep()
        while self.report.get('spent', 0) < self.options['max_sweeps']:
            self.check_deadline()
            found = self.catalogue()
            if found is None:
                return
            screen, rows = found
            screen, plan = self.configure_sweep(screen, rows, self.options['max_sweeps']-self.report.get('spent', 0))
            tag = str(len(self.report['history']))
            plan['before_evidence'] = str(self.ui.save('sweep_preview_'+tag, screen))
            self.click(screen, '一?键扫荡', (475, 435, 715, 525))
            screen = self.wait(field.bulk_confirmation, '追忆战扫荡最终确认')
            self.verify_confirmation(screen, plan)
            plan['confirmation'] = str(self.ui.save('sweep_confirmation_'+tag, screen))
            if self.options['preview_only']:
                self.report['sweep_preview'] = plan
                self.click(screen, '取消', (250, 440, 470, 520))
                screen = self.wait(field.bulk_catalogue, '取消扫荡最终确认')
                rows = field.sweep_rows(screen)
                if (self.ui.number(screen, (230, 375, 335, 415)) != plan['tickets_before']
                        or rows is None or any(not any(r.area == target['area'] and r.remaining == target['remaining']
                                                     for r in rows) for target in plan['targets'])):
                    raise RecollectionBlocked('取消预览后的余额或次数无法核对')
                self.report['sweep_preview']['cancelled'] = str(self.ui.save('sweep_preview_cancelled', screen))
                return
            self.state['pending_sweep'] = plan
            self.save()
            self.click(screen, '挑战', (480, 440, 710, 520))
            screen = self.wait(field.receipt, '追忆战扫荡结果')
            plan['receipt'] = str(self.ui.save('sweep_receipt_'+tag, screen))
            self.save()
            self.click(screen, '确认|关闭|确定', (250, 430, 720, 525))
            self.reconcile_sweep()
        self.report['budget_reached'] = True

    def run(self):
        try:
            if self.state.get('pending_battle'):
                raise RecollectionBlocked('首通战斗尚未核对，请先运行追忆战场首通复核进度')
            if self.enter() is None:
                self.report['status'] = 'unavailable'
                return self.finish()
            if self.state.get('pending_sweep'):
                self.report_progress('核对上次追忆战扫荡结果')
                self.reconcile_sweep()
            if self.state.get('pending_claim') or self.options['claim_rewards']:
                self.collect_rewards()
            if self.options['sweep_dominion']:
                self.sweep()
            if self.report.get('unsweepable'):
                self.report['pending'].append('部分领域尚未解锁扫荡：'+', '.join(self.report['unsweepable']))
            if self.report.get('budget_reached') and any(
                    self.report.get('remaining_attempts', {}).get(field.AREAS[k], 0)
                    for k in self.options['areas'] if field.AREAS[k] not in self.report.get('locked_areas', [])):
                self.report['pending'].append('达到本次扫荡次数上限，仍有未消费次数')
            self.report['status'] = ('partial' if self.report['pending'] else
                                     'prepared' if self.options['preview_only'] else
                                     'complete' if self.report['history'] else 'already_complete')
            return self.finish()
        except (RunCancelled, ResumeUnsafe) as error:
            self.report['status'] = 'cancelled' if isinstance(error, RunCancelled) else 'blocked'
            self.save()
            raise
        except EventUIError as error:
            return self.blocked(error)
