"""Stage D team battle: normal attacks that deal damage instead of killing.

From stage D one team rarely kills a boss, and any boss is an acceptable
target. An attack goes out only when its simulation meets the standard: a
kill, or ``damage_reference_percent`` of the recommendation's reference
damage. Recommendations are scanned in the game's damage order; each boss
gets at most ``damage_candidates`` simulations before the next boss is tried.
Extension attempts earned by an unexpected kill are left to the player.
With ``simulation_only`` the same choice runs as a rehearsal: a passing team
is recorded and counted as spent, and no attempt is used.
"""
from __future__ import annotations

from ..game_ui.screen import EventUIError
from ..game_ui.team_battle import Boss, damage_simulation_ready


class DamageAttacks:
    def __init__(self, task):
        self.task = task
        self.options = task.options
        self.task.damage_mode = True
        # Best simulated damage per five; same members, same damage.
        self.task.damage_results = {}

    def run(self):
        from .task_team_battle import BossChanged
        task, report = self.task, self.task.report
        report['mode'] = 'damage'
        rehearse = self.options.get('simulation_only', False)
        if rehearse:
            report['rehearsal'] = []
            # Simulations accept members already used in today's real attacks.
            task.restricted_words = '未持有'
        limit = self.options['max_real_attacks']
        changed = 0
        extension = 0
        while len(report['rehearsal'] if rehearse else report['battles']) < limit:
            task.check_deadline()
            task.report_progress(f"团队战D阶段 · 已出 {report['normal_attacks']} 刀",
                                 report['normal_attacks'], limit)
            screen = task.map()
            cp, extension = task.counts(screen)
            report['remaining_normal'], report['remaining_extension'] = cp, extension
            if cp == 0 and not rehearse:
                break
            screen, bosses = task.wait_bosses(screen)
            if not bosses:
                report['pending'].append('地图未出现可识别的首领轮次，可能仍在等待行会进度刷新')
                break
            try:
                row = self.attack_any(bosses, cp, extension)
            except BossChanged:
                changed += 1
                if changed > 3:
                    report['pending'].append('行会进度连续改变首领，已停止使用过期模拟结果')
                    break
                continue
            if row is None:
                counts = report.get('candidate_rejections', {})
                detail = '；累计淘汰：'+'、'.join(f'{k}{v}条' for k, v in sorted(counts.items())) if counts else ''
                left = (f'模拟预演第{len(report["rehearsal"])+1}刀未找到新队伍' if rehearse
                        else f'剩余{cp}次挑战需人工出刀')
                report['pending'].append(f'各首领均无模拟伤害达到参考伤害{self.options.get("damage_reference_percent", 70)}%'
                                         f'的可用队伍；{left}'+detail)
                break
            task.spent.add(row['team_key'])
            if rehearse:
                report['rehearsal'].append(row)
                task.save_report()
                continue
            report['normal_attacks'] += 1
            cp, extension = row['cp_after'], row['extension_after']
        if extension:
            report['pending'].append('伤害刀击杀首领获得延长次数；D阶段延长刀需人工处理')
        report['status'] = 'complete' if not report['pending'] else 'partial'
        return report

    def attack_any(self, bosses: list[Boss], cp: int, extension: int):
        """Any boss is acceptable: the most damaged first, so a passing team
        is tried where it moves the guild furthest."""
        for boss in sorted(bosses, key=lambda b: (b.lap, b.current_hp or 0, b.lane)):
            row = self.attack(boss, cp, extension)
            if row is not None:
                return row
        return None

    def attack(self, boss: Boss, cp: int, extension: int):
        from .task_team_battle import INCOMPLETE_TEAM, TaskDeadline
        task = self.task
        task.tried, task.tried_teams = set(), set()
        percent = self.options.get('damage_reference_percent', 70)
        for _ in range(self.options.get('damage_candidates', 3)):
            task.check_deadline()
            limit = self.options['max_simulations']
            if limit and len(task.report['simulations']) >= limit:
                raise TaskDeadline('达到程序设置的模拟搜索轮数上限；剩余挑战可继续搜索')
            task.report_progress(f"团队战D阶段 · {boss.name} · 查找伤害队伍")
            task.prepare_boss(boss, True)
            names = task.recommendation(boss_hp=boss.current_hp, boss_max=boss.maximum_hp)
            if names is None:
                task.ui.expect_click('取消', (560, 425, 755, 505), exact=True)
                task.map()
                return None
            gear = task.equipped(names)
            reference = task.teams[names].get('reference_damage')
            task.report_progress(f"团队战D阶段 · {boss.name} · 模拟第 {len(task.report['simulations'])+1} 队")
            simulation = task.battle(True, names, reference_damage=reference, boss_hp=boss.current_hp)
            task.report['simulations'].append(dict(boss=boss.name, lane=boss.lane, lap=boss.lap,
                                                   team_key=names, team=task.teams[names]['labels'],
                                                   reference_damage=reference, equipment=gear, **simulation))
            task.save_report()
            damage = boss.current_hp if simulation.get('win') else simulation.get('actual_damage') or 0
            task.damage_results[names] = max(damage, task.damage_results.get(names, 0))
            if not damage_simulation_ready(boss, simulation, reference, percent):
                task.reject_recommendation(f'模拟伤害未达参考伤害{percent}%', reference_damage=reference,
                                           actual_damage=simulation.get('actual_damage'))
                continue
            if self.options.get('simulation_only', False):
                return dict(boss=boss.name, lane=boss.lane, lap=boss.lap, team_key=names,
                            team=task.teams[names]['labels'], reference_damage=reference,
                            actual_damage=simulation.get('actual_damage'), win=simulation.get('win'))
            # The simulated five stay in the real formation; real_attack
            # re-checks members and gear before spending the attempt.
            row = task.real_attack(boss, names, gear, simulation, reference, cp, extension)
            if row is INCOMPLETE_TEAM:
                continue
            if row is None:
                raise EventUIError('伤害刀实战未返回结果')
            return row
        return None
