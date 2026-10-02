"""Bounded difficulty-one exploration, separate from repeat ticket sweeps."""
from __future__ import annotations

from .base import BaseTask
from .registry import register
from .task_dawn_labyrinth import DawnLabyrinth, SweepBlocked
from .dawn_labyrinth_party import LabyrinthFormation
from .event_battle import EventCombat
from ..game_ui import dawn_labyrinth as maze
from ..game_ui.screen import EventUI, EventUIError, normalized
from ..run_session import RunCancelled, ResumeUnsafe, clock as time


def validate_options(options):
    if not isinstance(options, dict):
        raise ValueError('DawnLabyrinthFirstClear必须是配置对象')
    value = dict(options)
    for key, default, upper in (('timeout', 1800, 7200), ('max_battles', 30, 60)):
        number = value.setdefault(key, default)
        if type(number) is not int or not 1 <= number <= upper:
            raise ValueError(f'DawnLabyrinthFirstClear.{key}必须是1到{upper}的整数')
    retry = value.setdefault('retry_failed_boss', False)
    if type(retry) is not bool:
        raise ValueError('DawnLabyrinthFirstClear.retry_failed_boss必须是布尔值')
    return value


@register('dawn_labyrinth_first_clear', requires_home=False)
class DawnLabyrinthFirstClear(DawnLabyrinth):
    config_section = 'DawnLabyrinthFirstClear'

    @classmethod
    def prepare(cls, config, *args, **kwargs):
        validate_options(config.get(cls.config_section, {}))
        return args, kwargs, None

    def __init__(self, robot):
        BaseTask.__init__(self, robot)
        self.options = validate_options(self.task_options())
        self.ui = EventUI(self.driver, self.options.get('output', 'cache/daily/dawn_labyrinth_first_clear'))
        self.deadline = time.monotonic() + self.options['timeout']
        self.report = dict(status='running', difficulty=1, guild='美食殿堂', initial_passes=None,
                           remaining_passes=None, spent=0, entries=0, battles=0,
                           pending=[], history=[])
        self.formation = None
        self.exploration_verified = False

    def enter(self):
        screen = self.capture()
        if maze.sweep_catalogue(screen):
            self.ui.click(screen.find('取消', (480, 440, 695, 520), exact=True))
            screen = self.wait(lambda s: maze.home(s) or maze.guild_selection(s), '关闭跳过公会一览')
        if maze.damage_report(screen):
            self.ui.click(screen.find('确认', (320, 440, 650, 520), exact=True))
            screen = self.wait(lambda s: not maze.damage_report(s), '关闭迷宫伤害报告')
        if screen.find('魔物详情', (240, 0, 720, 100), exact=True):
            close = screen.find('关闭', (320, 430, 650, 515), exact=True)
            if not close:
                raise SweepBlocked('魔物详情无法安全关闭')
            self.ui.click(close)
            screen = self.capture()
        if screen.find('角色详情', (240, 0, 720, 125), exact=True):
            button = screen.find('确认|关闭', (320, 430, 650, 515), exact=True)
            if not button:
                raise SweepBlocked('角色详情无法安全关闭')
            self.ui.click(button)
            screen = self.capture()
        if maze.settlement_screen(screen):
            self.report['settlement_resumed'] = True
            return screen
        if (screen.find('角色选择|出发奖励|角色加入', (240, 0, 720, 125), exact=True)
                or maze.invitation_animation(screen) or maze.exploration_map(screen) or maze.battle_detail(screen)
                or maze.invitation_reward(screen) or maze.movement_confirmation(screen)
                or maze.event_screen(screen) or maze.receipt(screen) or maze.relic_reward(screen)
                or maze.shop(screen)
                or maze.boss_failure(screen) or maze.clear_receipt(screen)
                or screen.find('WIN!?', (280, 0, 680, 210), exact=True)):
            return screen
        if screen.find('队伍编组', (300, 0, 650, 70), exact=True):
            if maze.selected_boss_team(screen) is not None:
                self.ui.click(screen.find('队伍1', (40, 65, 160, 110), exact=True))
                screen = self.wait(lambda s: maze.selected_boss_team(s) == 1, '返回首领第一队')
            cancel = screen.find('取消', (630, 405, 795, 500), exact=True)
            if not cancel:
                raise SweepBlocked('未确认迷宫编队的取消按钮')
            self.ui.click(cancel)
            return self.wait(maze.battle_detail, '返回迷宫战斗详情')
        if maze.departure_confirmation(screen):
            cancel = screen.find('取消', (150, 440, 375, 520), exact=True)
            if not cancel:
                raise SweepBlocked('出发确认无法安全关闭')
            self.ui.click(cancel)
            screen = self.wait(maze.guild_selection, '返回公会选择')
        if screen.find('难度变更', (240, 0, 720, 75), exact=True):
            cancel = screen.find('取消', (255, 450, 465, 515), exact=True)
            if not cancel:
                raise SweepBlocked('难度选择窗口无法安全关闭')
            self.ui.click(cancel)
            screen = self.wait(maze.guild_selection, '关闭难度选择')
        if maze.guild_selection(screen):
            self.ui.click((30, 30))
            return self.wait(maze.home, '返回迷宫首页')
        return super().enter()

    def difficulty_one(self, screen):
        change = screen.find('难度变更', (800, 0, 885, 100), exact=True)
        if not change:
            raise SweepBlocked('首通难度选择入口无法确认')
        self.ui.click(change)
        screen = self.wait(lambda s: s.find('难度变更', (240, 0, 720, 75), exact=True), '迷宫难度选择')
        for _ in range(3):
            target = screen.find('难度1', (285, 65, 400, 395), exact=True)
            if target:
                break
            self.ui.swipe((615, 165), (615, 395))
            screen = self.capture()
        if not target:
            raise SweepBlocked('尚不能验证其他难度，首通任务只支持难度1')
        if maze.selected_difficulty(screen) == 1:
            button = screen.find('取消', (255, 450, 465, 515), exact=True)
        else:
            self.ui.click((283, int(target.center[1]) + 31))
            screen = self.capture()
            if maze.selected_difficulty(screen) != 1:
                raise SweepBlocked('难度1的选择状态无法核对')
            button = screen.find('变更', (480, 450, 705, 515), exact=True)
            if not screen.blue_button(button):
                raise SweepBlocked('难度变更按钮未启用')
        if not button:
            raise SweepBlocked('难度选择窗口无法关闭')
        self.ui.click(button)
        return self.wait(maze.guild_selection, '迷宫公会选择')

    def start(self, screen):
        before = self.balance(screen)
        self.report.update(initial_passes=before, remaining_passes=before)
        departure = screen.find('出发', (480, 250, 695, 330), exact=True)
        if not departure:
            raise SweepBlocked('迷宫已有探索，需要从实际进度接续')
        self.ui.click(departure)
        screen = self.wait(lambda s: maze.guild_selection(s) or maze.exploration_map(s)
                           or maze.battle_detail(s) or maze.boss_failure(s)
                           or maze.selected_boss_team(s) is not None, '迷宫公会选择或接续探索')
        if not maze.guild_selection(screen):
            self.report['resumed'] = True
            return self.enter()
        screen = self.difficulty_one(screen)
        screen = self.check_unlock(screen)
        if screen is None:
            return None
        if before < 1:
            raise SweepBlocked('未持有迷宫通行证，无法完成有报酬的首通')
        guild = screen.find('美食殿堂', (50, 320, 250, 390), exact=True)
        choose = screen.find('选择', (70, 380, 215, 465), exact=True)
        if not guild or not choose or not screen.blue_button(choose):
            raise SweepBlocked('未确认美食殿堂首通入口')
        self.ui.click(choose)
        screen = self.wait(maze.departure_confirmation, '迷宫首通出发确认')
        preview = maze.departure_preview(self.ui, screen)
        if preview[0] != before:
            raise SweepBlocked('迷宫通行证数量已变化，未出发')
        button = screen.find('出发', (610, 440, 825, 520), exact=True)
        if not screen.blue_button(button):
            raise SweepBlocked('迷宫首通出发按钮不可用')
        path = self.ui.save('departure_preview', screen)
        self.report['pending_spend'] = dict(before=before, after=preview[1], cost=1, preview=str(path))
        self.report['entries'] = 1
        self.save_report()
        self.ui.click(button)
        self.exploration_verified = True
        time.sleep(2)
        return self.capture()

    def check_unlock(self, screen):
        skip = screen.find(maze.SWEEP, (870, 0, 955, 100), exact=True)
        if not skip:
            raise SweepBlocked('难度1的首通状态无法核对，未出发')
        self.ui.click(skip)
        screen = self.wait(lambda s: maze.locked_notice(s) or maze.sweep_confirmation(s)
                           or maze.sweep_guild_selection(s), '难度1首通状态', timeout=15)
        if maze.locked_notice(screen):
            self.ui.save('first_clear_required', screen)
            return self.wait(lambda s: maze.guild_selection(s) and not maze.locked_notice(s), '首通提示消失')
        proof = self.ui.save('already_cleared', screen)
        if maze.sweep_catalogue(screen) and not any(g.text == '美食殿堂' for g in maze.catalogue_guilds(screen)):
            raise SweepBlocked('可跳过列表未确认美食殿堂，未再次出发')
        cancel = screen.find('取消|关闭', (200, 395, 750, 520), exact=True)
        if not cancel:
            raise SweepBlocked('难度1已可跳过，但窗口关闭入口尚未核对；未出发')
        self.ui.click(cancel)
        screen = self.wait(lambda s: maze.guild_selection(s) or maze.home(s), '关闭跳过预览')
        if maze.guild_selection(screen):
            self.ui.click((30, 30))
            screen = self.wait(maze.home, '返回迷宫首页')
        self.report.update(status='complete', already_cleared=True, clear_evidence=str(proof),
                           remaining_passes=self.balance(screen))
        return None

    def verify_exploration(self, screen):
        if not maze.exploration_menu(screen):
            menu = screen.find('菜单', (880, 0, 960, 85), exact=True)
            if not menu:
                raise EventUIError('当前探索难度无法确认，未继续战斗')
            self.ui.click(menu)
            screen = self.wait(maze.exploration_menu, '当前探索菜单')
        x, y = screen.find('难度详情', (680, 85, 805, 265), exact=True).center
        difficulty = self.ui.number(screen, (int(x)-8, int(y)-30, int(x)+11, int(y)-4))
        if difficulty != 1:
            raise EventUIError('当前探索不是已核验的难度1，已保留进度')
        self.report['difficulty_evidence'] = str(self.ui.save('current_difficulty', screen))
        self.exploration_verified = True
        menu = screen.find('菜单', (880, 0, 960, 85), exact=True)
        if not menu:
            raise EventUIError('当前探索菜单无法关闭')
        self.ui.click(menu)
        return self.wait(lambda s: not maze.exploration_menu(s), '关闭当前探索菜单')

    def explore(self, screen):
        if screen.find('出发奖励', (240, 0, 720, 75), exact=True):
            self.ui.click(screen.find('关闭', (320, 450, 650, 515), exact=True))
            screen = self.wait(lambda s: s.find('角色选择', (300, 0, 650, 70), exact=True), '初始伙伴选择')
        if screen.find('角色选择', (300, 0, 650, 70), exact=True):
            self.report_progress('准备公共角色头像并核对初始伙伴')
            self.report['partners'] = self.get_formation().choose_initial(screen)
            self.save_report()
            time.sleep(2)
            screen = self.capture()
        unknown_since = time.monotonic()
        for _ in range(300):
            handled = True
            if maze.boss_failure(screen):
                if not self.options['retry_failed_boss'] or self.report.get('boss_retry'):
                    raise EventUIError('首领失败已保留；未启用本次首领重新挑战，不自动重试')
                self.report['boss_retry'] = True
                self.save_report()
                self.ui.click(screen.find('重新挑战', (700, 470, 930, 535), exact=True))
                screen = self.wait(lambda s: maze.selected_boss_team(s) is not None, '首领重新编组')
                self.ui.click(screen.find('队伍1', (40, 65, 160, 110), exact=True))
                screen = self.wait(lambda s: maze.selected_boss_team(s) == 1, '首领第一队')
                self.ui.click(screen.find('取消', (630, 405, 795, 500), exact=True))
                screen = self.wait(maze.battle_detail, '首领敌方重新核对')
                continue
            if (maze.home(screen) and not maze.settlement_screen(screen) and not maze.receipt(screen)
                    and (self.report.get('boss_defeated') or self.report.get('settlement_resumed'))):
                remaining = self.balance(screen)
                pending = self.report.get('pending_spend')
                if pending and remaining != pending['after']:
                    raise EventUIError('首通后通行证余额与出发预览不符')
                self.ui.save('clear_balance', screen)
                # Unlocking the next difficulty selects it automatically. Restore
                # difficulty one and prove its guild is sweepable before finishing,
                # including resumed partial-reward results.
                self.ui.click(screen.find('出发', (480, 250, 695, 330), exact=True))
                guild = self.wait(maze.guild_selection, '结算后的首通状态')
                guild = self.difficulty_one(guild)
                if self.check_unlock(guild) is not None:
                    raise EventUIError('探索奖励已结算，但难度1仍未解锁跳过；未再次出发')
                if pending:
                    self.report['spent'] += pending['cost']
                    self.report['history'].append(dict(self.report.pop('pending_spend'), outcome='cleared'))
                self.report.update(status='complete', remaining_passes=remaining)
                return
            if (not self.exploration_verified and not self.report.get('settlement_resumed')
                    and (maze.exploration_menu(screen) or maze.exploration_map(screen)
                         or maze.battle_detail(screen) or maze.relic_reward(screen)
                         or maze.event_screen(screen) or maze.invitation_reward(screen))):
                screen = self.verify_exploration(screen)
                continue
            if maze.invitation_animation(screen):
                self.ui.click((480, 270))
            elif maze.invitation_reward(screen):
                self.report.setdefault('additional_partners', []).append(self.get_formation().choose_reward(screen))
                self.save_report()
            elif maze.event_screen(screen):
                choice = maze.free_event_choice(screen)
                if not choice:
                    raise EventUIError('随机事件的资源变化尚未验证，保留进度且未选择')
                self.ui.save('free_event', screen)
                self.ui.click(choice)
            elif maze.shop_exit(screen):
                confirm = screen.find('确认', (480, 335, 710, 405), exact=True)
                if not screen.blue_button(confirm):
                    raise EventUIError('迷宫商店退出确认不可用，未购买')
                self.ui.click(confirm)
                screen = self.wait(maze.exploration_map, '离开迷宫商店')
                unknown_since = time.monotonic()
                continue
            elif maze.shop(screen):
                close = screen.find('关闭', (710, 420, 930, 520), exact=True)
                if not close:
                    raise EventUIError('迷宫商店关闭按钮无法确认，未购买')
                self.ui.click(close)
                screen = self.wait(lambda s: maze.shop_exit(s) or maze.exploration_map(s), '迷宫商店退出确认')
                unknown_since = time.monotonic()
                continue
            elif maze.relic_reward(screen):
                choice = maze.positive_relic_choice(screen)
                if not choice:
                    raise EventUIError('遗物效果尚未核对，保留进度且未选择')
                self.ui.save('relic_choice', screen)
                self.ui.click(choice)
            elif screen.find('WIN!?', (280, 0, 680, 210), exact=True):
                button = screen.find('下一步', (700, 425, 950, 525), exact=True)
                if button:
                    self.ui.click(button)
                else:
                    time.sleep(.5)
            elif screen.find('角色加入', (240, 0, 720, 125), exact=True):
                button = screen.find('关闭', (320, 390, 650, 515), exact=True)
                if not button:
                    raise EventUIError('伙伴加入回执无法关闭')
                self.ui.click(button)
            elif maze.inventory_result(screen):
                self.ui.save('clear_inventory', screen)
                self.ui.click(screen.find('下一步', (320, 450, 650, 525), exact=True))
            elif maze.score_result(screen):
                self.report['clear_score_evidence'] = str(self.ui.save('clear_score', screen))
                if screen.find('CLEAR', (150, 75, 340, 165), exact=True):
                    self.report['boss_defeated'] = True
                self.save_report()
                self.ui.click(screen.find('关闭', (320, 450, 650, 525), exact=True))
            elif maze.difficulty_unlock(screen):
                self.ui.save('difficulty_unlock', screen)
                self.ui.click(screen.find('关闭', (320, 335, 650, 415), exact=True))
            elif maze.receipt(screen):
                button = screen.find('关闭|确认', (320, 390, 750, 520), exact=True)
                if not button:
                    raise EventUIError('迷宫节点奖励回执无法关闭')
                self.ui.save('node_reward', screen)
                self.ui.click(button)
            elif self.report.get('boss_defeated') and maze.clear_receipt(screen):
                button = screen.find('全部开启|全部打开|确认|关闭|返回迷宫', (200, 395, 930, 525), exact=True)
                if not button:
                    raise EventUIError('通关奖励回执的继续按钮无法确认')
                self.ui.save('clear_result', screen)
                self.ui.click(button)
            elif maze.battle_detail(screen):
                screen = self.fight(screen)
                unknown_since = time.monotonic()
                continue
            elif maze.movement_confirmation(screen):
                button = screen.find('确认', (480, 335, 710, 405), exact=True)
                if not screen.blue_button(button):
                    raise EventUIError('迷宫节点移动确认不可用')
                self.ui.click(button)
                screen = self.wait(lambda s: not maze.exploration_map(s) and not maze.movement_confirmation(s),
                                   '迷宫节点内容')
                unknown_since = time.monotonic()
                continue
            elif maze.exploration_map(screen):
                nodes = maze.reachable_nodes(screen)
                node = min(nodes, key=lambda item: (item.center[0], item.center[1])) if nodes else maze.unlabelled_node(screen)
                if node is None:
                    if time.monotonic() - unknown_since > 12:
                        self.ui.save('exploration_state', screen)
                        raise EventUIError('当前可行动节点不是已验证战斗类型，已保留探索进度')
                    time.sleep(.5)
                    screen = self.capture()
                    continue
                self.report_progress('推进迷宫节点', self.report['battles'], self.options['max_battles'])
                self.ui.click(node)
                screen = self.wait(lambda s: maze.movement_confirmation(s) or maze.battle_detail(s)
                                   or maze.event_screen(s) or maze.relic_reward(s), '迷宫节点进入')
                unknown_since = time.monotonic()
                continue
            else:
                handled = False
                if time.monotonic() - unknown_since > 12:
                    self.ui.save('exploration_state', screen)
                    raise EventUIError('迷宫探索页面无法确认，已保留当前进度')
                time.sleep(.5)
            if handled:
                unknown_since = time.monotonic()
            screen = self.capture()
        raise EventUIError('迷宫探索达到步骤上限，已保留当前进度')

    def check_deadline(self):
        if time.monotonic() >= self.deadline:
            raise EventUIError('首通任务达到运行时限')

    def get_formation(self):
        if self.formation is None:
            self.formation = LabyrinthFormation(self.ui)
            self.report['assets'] = self.formation.prepare_assets(self.check_deadline)
        return self.formation

    def story_dialog(self, screen):
        return False

    def inspect_enemies(self, screen):
        boss_stage = bool(screen.find('首领战格子', (30, 15, 500, 90), exact=True))
        information = maze.enemy_information(screen)
        labels = screen.all(r'^Lv\.?\d+$', (60, 280, 890, 350))
        if not information or len(information) < len(labels):
            raise EventUIError('迷宫敌方信息按钮无法完整核对，未开战')
        enemies = []
        for index, button in enumerate(information):
            self.ui.click(button)
            detail = self.wait(lambda s: s.find('魔物详情', (240, 0, 720, 100), exact=True), '迷宫魔物详情')
            name = detail.find('.+', (270, 60, 675, 105))
            hp = detail.find(r'\d+/\d+', (480, 140, 700, 180), exact=True)
            level = self.ui.number(detail, (615, 110, 700, 145))
            if not name or name.score < .95 or not hp or hp.score < .95 or level is None or not 1 <= level <= 380:
                raise EventUIError('迷宫敌方身份、等级或生命值无法核对，未开战')
            current, maximum = map(int, normalized(hp.text).split('/'))
            text = normalized(detail.text((260, 205, 700, 435)))
            enemy_name = normalized(name.text)
            if boss_stage and enemy_name == '暗黑滴水嘴兽':
                effects = normalized(detail.text((275, 220, 675, 275)))
                parts = [text]
                for _ in range(4):
                    self.ui.swipe((525, 425), (525, 260))
                    detail = self.capture()
                    part = normalized(detail.text((260, 205, 700, 435)))
                    parts.append(part)
                    if part == parts[-2] and '魔法固定伤害' in part:
                        break
                else:
                    raise EventUIError('首领技能末尾尚未核对，未开战')
                text = ''.join(dict.fromkeys(parts))
                supported = maze.supported_boss(enemy_name, level, maximum, effects, text)
            else:
                supported = maze.supported_normal_enemy(maximum, text)
            if not 0 < current <= maximum or not supported:
                raise EventUIError('迷宫敌方有未支持的特殊机制，未开战')
            proof = self.ui.save(f'enemy_{index:02d}', detail)
            enemies.append(dict(name=enemy_name, level=level,
                                hp=current, maximum_hp=maximum, description=text, evidence=str(proof)))
            close = detail.find('关闭', (320, 430, 650, 515), exact=True)
            if not close:
                raise EventUIError('魔物详情无法安全关闭')
            self.ui.click(close)
            screen = self.wait(maze.battle_detail, '返回战斗详情')
        if boss_stage and sum(enemy['name'] == '暗黑滴水嘴兽' for enemy in enemies) != 1:
            raise EventUIError('当前首领尚无已核验的试打条件，未开战')
        return enemies, screen

    def fight(self, screen):
        if not self.exploration_verified:
            raise EventUIError('尚未确认当前探索难度，未开战')
        if self.report['battles'] >= self.options['max_battles']:
            raise EventUIError('达到本次战斗次数上限，已保留探索进度')
        boss_stage = bool(screen.find('首领战格子', (30, 15, 500, 90), exact=True))
        if not boss_stage and not screen.find(r'战斗格子\(普通\)', (30, 15, 500, 90), exact=True):
            raise EventUIError('特殊战斗的敌方机制尚未核验，已保留探索进度')
        enemies, screen = self.inspect_enemies(screen)
        levels = [enemy['level'] for enemy in enemies]
        self.ui.click(screen.find('挑战', (715, 415, 930, 510), exact=True))
        self.wait(lambda s: s.find('队伍编组', (300, 0, 650, 70), exact=True), '迷宫编队')
        self.report_progress('核对迷宫队伍并开始战斗')
        formation = self.get_formation()
        if boss_stage:
            screen = self.capture()
            if maze.selected_boss_team(screen) != 1:
                raise EventUIError('首领第一队无法核对，未开战')
            screen = formation.clear_current()
            for number in (2, 3):
                next_team = screen.find('队伍'+str(number), (775, 405, 930, 500), exact=True)
                if not screen.blue_button(next_team):
                    raise EventUIError('首领编队切换入口无法核对，未开战')
                self.ui.click(next_team)
                self.wait(lambda s: maze.selected_boss_team(s) == number, '首领队伍'+str(number))
                screen = formation.clear_current()
            self.ui.click(screen.find('队伍1', (40, 65, 160, 110), exact=True))
            self.wait(lambda s: maze.selected_boss_team(s) == 1, '首领伙伴盘点')
            ready, roles = formation.audit_boss_roster()
            names = formation.plan_boss_parties(ready, roles)
            self.report['boss_roster'] = {n: vars(s) for n, s in ready.items()}
            teams = []
            for number, members in enumerate(names, 1):
                party, screen = formation.select_members(members, max(levels), boss=True)
                teams.append(party)
                if number < 3:
                    button = screen.find('队伍'+str(number+1), (775, 405, 930, 500), exact=True)
                    if not screen.blue_button(button):
                        raise EventUIError('首领编队切换入口无法核对，未开战')
                    self.ui.click(button)
                    self.wait(lambda s: maze.selected_boss_team(s) == number+1, '首领队伍'+str(number+1))
            self.report['boss_teams'] = teams
            party = teams[0]
        else:
            party, screen = formation.select_standard(max(levels))
        start = screen.find('战斗开始', (775, 405, 930, 500), exact=True)
        if not screen.blue_button(start):
            raise EventUIError('迷宫战斗开始按钮未启用')
        self.report['pending_battle'] = dict(kind='boss' if boss_stage else 'normal', enemy_level=max(levels), enemies=enemies, party=party,
                                           preview=str(self.ui.save('battle_preview', screen)))
        self.save_report()
        self.ui.click(start)
        combat = EventCombat(self)
        configured = False
        until = min(self.deadline, time.monotonic()+(420 if boss_stage else 220))
        for _ in range(600 if boss_stage else 300):
            if time.monotonic() >= until:
                break
            screen = self.capture()
            failed = maze.boss_failure(screen) if boss_stage else screen.find('战斗失败|挑战失败|LOSE|DEFEAT|TIMEUP|时间到')
            if failed:
                self.report['battles'] += 1
                proof = self.ui.save('battle_failed', screen)
                self.report['history'].append(dict(self.report.pop('pending_battle'), outcome='failed', result=str(proof)))
                self.save_report()
                raise EventUIError('迷宫战斗未获胜，保留进度且不自动重试')
            if screen.find('WIN|战斗胜利|胜利') or combat.match('btn_next_step', screen):
                self.report['battles'] += 1
                if boss_stage:
                    self.report['boss_defeated'] = True
                proof = self.ui.save(f"battle_{self.report['battles']:02d}_result", screen)
                self.report['history'].append(dict(self.report.pop('pending_battle'), result=str(proof)))
                self.save_report()
                button = screen.find('下一步|确认', (400, 380, 940, 520), exact=True) or combat.match('btn_next_step', screen)
                if button:
                    self.ui.click(button)
                return self.capture()
            if not configured and (screen.find('主菜单') or combat.match('btn_menu_text', screen)):
                configured = combat.configure_paused(None, [])
            time.sleep(.5)
        raise EventUIError('迷宫战斗结果未确认，保留现场且不自动重试')

    def run(self):
        try:
            self.report_progress('准备黎明界迷宫难度1首通')
            screen = self.enter()
            if screen is None:
                self.report.update(status='unavailable', reason='冒险页未找到黎明界迷宫入口')
                return self.report
            if maze.home(screen) and not self.report.get('settlement_resumed'):
                screen = self.start(screen)
                if screen is None:
                    self.collect_mission_rewards()
                    return self.report
            else:
                self.report['resumed'] = True
            self.explore(screen)
            self.collect_mission_rewards()
        except EventUIError as error:
            self.report['status'] = ('partial' if self.report.get('pending_spend') or self.report.get('resumed')
                                     or self.report.get('already_cleared') or self.report.get('boss_defeated')
                                     or self.report.get('pending_mission_claim') else 'blocked')
            if self.report.get('missions'):
                self.report['missions']['status'] = self.report['status']
            self.report['pending'].append(str(error))
            if self.ui.last is not None:
                self.ui.save('blocked', self.ui.last)
        except (RunCancelled, ResumeUnsafe) as error:
            self.report['status'] = 'cancelled' if isinstance(error, RunCancelled) else 'error'
            if self.report.get('missions'):
                self.report['missions']['status'] = self.report['status']
            self.report['pending'].append(str(error))
            raise
        except Exception as error:
            self.report['status'] = 'error'
            if self.report.get('missions'):
                self.report['missions']['status'] = 'error'
            self.report['pending'].append(str(error))
            raise
        finally:
            self.save_report()
        return self.report
