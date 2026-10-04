"""Synthetic first-entry safety and current-exploration regressions."""
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2 as cv

from pcrscript import Robot
from pcrscript.game_ui import dawn_labyrinth as maze
from pcrscript.game_ui.screen import EventUIError
from pcrscript.run_session import RunCancelled
from pcrscript.runtime import run_task_with_config
from pcrscript.tasks import DawnLabyrinth, DawnLabyrinthFirstClear
from pcrscript.tasks.dawn_labyrinth_party import LabyrinthFormation, LabyrinthBossStrategy
from pcrscript.tasks.event_strategy import CharacterStatus, EventParty, MemberRequirement
from pcrscript.tasks.party_variants import character_roles
from test_dawn_labyrinth import screen, home, guild, preview, catalogue, bulk, mission_home, missions, mission_receipt


def difficulty(selected=1):
    value = screen(('难度变更', 480, 42), ('难度1', 330, 123),
                   ('难度2', 330, 223), ('取消', 370, 480), ('变更', 588, 480), blue=('变更',))
    cv.rectangle(value.image, (274, 123+22+100*(selected-1)),
                 (291, 123+39+100*(selected-1)), (230, 155, 25), -1)
    return value


def departure(before=11, after=10):
    return screen(('公会选择确认', 480, 42),
                  ('将消耗1张迷宫通行证和【美食殿堂】一同出发。确定吗？', 480, 85),
                  ('持有迷宫通行证', 350, 427), (str(before), 565, 427), (str(after), 692, 427),
                  ('取消', 255, 475), ('出发', 705, 475), blue=('出发',))


def zero_departure(guild_name='美食殿堂'):
    return screen(('公会选择确认', 480, 42),
                  (f'【{guild_name}】一同出发。', 480, 85),
                  ('由于未持有迷宫通行证，无法获得报酬。', 480, 415),
                  ('取消', 255, 475), ('出发', 705, 475), blue=('出发',))


def cleared_preview(before=11, after=10, guild_name='美食殿堂'):
    value = preview(before, after)
    if guild_name is not None:
        value.items.extend(screen((guild_name, 480, 200)).items)
    return value


def sweep_guild_choice(guild_name='美食殿堂', enabled=True):
    value = screen(('黎明界迷宫', 130, 30), ('请选择要跳过的公会', 480, 88),
                   (guild_name, 144, 352), ('跳过', 144, 422),
                   ('合成公会', 413, 352), ('跳过', 413, 422), ('取消', 480, 505))
    for x in ((144, 413) if enabled else (413,)):
        cv.rectangle(value.image, (x-50, 398), (x+50, 446), (230, 155, 25), -1)
    return value


def normal_enemy_detail(description=None):
    description = ('【物理】【防御】住在高山上,厚实的毛皮之下拥有强韧的身体,驯鹿魔物。·近身攻击·造成伤害所获得的技能值回复量降低80%'
                   if description is None else description)
    return screen(('魔物详情', 480, 42), ('雪原山羊', 480, 80), ('370', 650, 127),
                  ('700000/700000', 590, 160), (description, 480, 300), ('关闭', 480, 480))


def boss_intro():
    return '【物理】侍奉着暴食君主的近卫黑铁像。徘徊于冥府,巧妙地操纵灵魂并将其奉献给主人。'


def boss_description():
    return ('【特殊效果】·所有的技能伤害无法回复技能值'
            '【必杀技能】·对进行物理攻击的敌方全体赋予烧伤状态'
            '·自身的物理防御力越高：伤害越大'
            '·对进行魔法攻击的敌方全体赋予烧伤状态'
            '·自身的魔法防御力越高：伤害越大'
            '·降低敌方全体生命值吸收量'
            '【技能1】·对敌方全体造成魔法伤害·击退敌方全体（必中）'
            '·对前方一名敌人造成魔法固定伤害')


def boss_enemy_detail(description=None):
    value = screen(('魔物详情', 480, 42), ('暗黑滴水嘴兽', 480, 80), ('350', 650, 127),
                   ('60000000/60000000', 590, 160), ('对怪物的有效效果', 480, 222),
                   ('坦克型', 325, 250), ('物防下降', 470, 250), ('魔防下降', 605, 250),
                   (boss_description() if description is None else description, 480, 330), ('关闭', 480, 480))
    return value


def inventory_result():
    return screen(('难度1', 480, 27), ('RESULT', 480, 62), ('加入的角色', 160, 103),
                  ('已获得的迷宫遗物', 200, 285), ('下一步', 480, 497))


def score_result(clear=True):
    return screen(('难度1', 480, 27), ('RESULT', 480, 62), ('CLEAR' if clear else 'RETURN', 242, 110),
                  ('分数明细', 175, 236), ('难度奖励', 390, 425), ('关闭', 480, 497))


def ready_character(name, **changes):
    return CharacterStatus(**dict(dict(name=name, level=365, rank=38, stars=6, skill_level=365,
                                       identity_verified=True, equipment=6, unique=True, unique2=False,
                                       equipment_evidence='synthetic-equipment'), **changes))


def boss_formation(selected):
    action = '队伍'+str(selected+1) if selected < 3 else '战斗开始'
    value = screen(('队伍编组', 480, 42), ('队伍1', 98, 89),
                   ('队伍2', 216, 89), ('队伍3', 334, 89),
                   ('取消', 712, 453), (action, 851, 453), blue=(action,))
    left = 69+118*(selected-1)
    cv.rectangle(value.image, (left, 82), (left+59, 97), (40, 190, 245), -1)
    return value


def boss_roster():
    names = ('佩可莉姆', '可可萝', '凯露')+tuple(f'合成伙伴{i}' for i in range(12))
    ready = {name: ready_character(name, stars=6 if name in names[:3] else 5) for name in names}
    roles = {name: dict(role=1, kind=1, score=50, single=1) for name in names}
    return ready, roles


def synthetic_boss_strategy(groups=None):
    core = ('佩可莉姆', '可可萝', '凯露')
    names = list(core)+[f'合成伙伴{i}' for i in range(12)]
    groups = groups or (names[:5], names[5:10], names[10:15])
    parties = tuple(EventParty('合成已验证队伍'+str(index), 'synthetic://boss-source',
                              [MemberRequirement(name, 365 if name in core else 350, 38,
                                                 6 if name in core else 5, unique=True, unique2=False,
                                                 skill_level=365 if name in core else 350, equipment=6,
                                                 exact_rank=False, exact_stars=False)
                               for name in group])
                    for index, group in enumerate(groups))
    return LabyrinthBossStrategy('cn', '美食殿堂', 1, '暗黑滴水嘴兽', 350, 60000000,
                                 parties, 'synthetic-verified-source', verified=True)


class FirstClearRecognitionTests(TestCase):
    def test_zero_pass_preview_is_recognized_but_cannot_authorize_paid_departure(self):
        value = zero_departure()
        self.assertTrue(maze.unrewarded_departure_confirmation(value))
        self.assertTrue(maze.departure_confirmation(value))
        # Even stray balance text cannot turn the no-reward preview into paid evidence.
        value.items.extend(departure().items[2:5])
        ui = Mock(number=Mock(side_effect=lambda s, roi: s.number(roi)))
        with self.assertRaises(EventUIError):
            maze.departure_preview(ui, value)
        ui.number.assert_not_called()
        self.assertFalse(maze.departure_confirmation(zero_departure('合成公会')))
        low = zero_departure()
        low.items[2].score = .94
        self.assertFalse(maze.departure_confirmation(low))

    def test_clear_guild_evidence_covers_each_sweep_layout(self):
        for value in (catalogue(selected=False), cleared_preview(),
                      sweep_guild_choice(), bulk()):
            with self.subTest(page=value.text()):
                proof = maze.sweep_guild_evidence(value, '美食殿堂')
                self.assertIsNotNone(proof)
                self.assertEqual(proof.text, '美食殿堂')
                self.assertIsNone(maze.sweep_guild_evidence(value, '未通关公会'))

    def test_clear_guild_evidence_rejects_background_names_and_unavailable_cards(self):
        background = cleared_preview(guild_name='合成公会')
        background.items.extend(screen(('美食殿堂', 144, 352)).items)
        unknown = cleared_preview(guild_name=None)
        low_confidence = cleared_preview()
        low_confidence.items[-1].score = .94
        locked_card = sweep_guild_choice()
        locked_card.items.extend(screen(('未通关', 144, 320)).items)
        low_button = sweep_guild_choice()
        low_button.find('跳过', (100, 400, 200, 440), exact=True).score = .94
        for value in (background, unknown, low_confidence, locked_card,
                      low_button, sweep_guild_choice(enabled=False),
                      sweep_guild_choice(guild_name='合成公会'), cleared_preview(guild_name='美食殿堂未通关'),
                      guild(('美食殿堂', 144, 352))):
            with self.subTest(page=value.text()):
                self.assertIsNone(maze.sweep_guild_evidence(value, '美食殿堂'))

    def test_three_boss_team_tabs_require_one_gold_selection(self):
        value = screen(('队伍编组', 480, 42), ('队伍1', 98, 89),
                       ('队伍2', 216, 89), ('队伍3', 334, 89))
        self.assertIsNone(maze.selected_boss_team(value))
        cv.rectangle(value.image, (187, 82), (246, 97), (40, 190, 245), -1)
        self.assertEqual(maze.selected_boss_team(value), 2)
        cv.rectangle(value.image, (305, 82), (364, 97), (40, 190, 245), -1)
        self.assertIsNone(maze.selected_boss_team(value))

    def test_generic_roles_without_boss_strategy_cannot_authorize_parties(self):
        ready, roles = boss_roster()
        with self.assertRaises(EventUIError):
            LabyrinthFormation.plan_boss_parties(ready, roles)

    def test_boss_strategy_requires_verified_context_and_complete_source_requirements(self):
        ready, roles = boss_roster()
        valid = synthetic_boss_strategy()
        for fields in ({'verified': False}, {'evidence': ''}, {'server': 'tw'}, {'guild': '合成其他公会'},
                       {'difficulty': 2}, {'boss': '合成其他首领'}, {'level': 351}, {'maximum_hp': 60000001},
                       {'parties': None}, {'parties': ()}):
            with self.subTest(fields=fields), self.assertRaises(EventUIError):
                LabyrinthFormation.plan_boss_parties(ready, roles, strategy=replace(valid, **fields))
        for field, value in (('source', ''), ('auto', False), ('assumptions', ['未知条件']),
                             ('modes', None), ('modes', [True]), ('members', None)):
            changed = synthetic_boss_strategy()
            setattr(changed.parties[0], field, value)
            with self.subTest(field=field), self.assertRaises(EventUIError):
                LabyrinthFormation.plan_boss_parties(ready, roles, strategy=changed)
        changed = synthetic_boss_strategy()
        changed.parties[0].members[-1].unique = None
        with self.assertRaises(EventUIError):
            LabyrinthFormation.plan_boss_parties(ready, roles, strategy=changed)

    def test_boss_pool_requires_verified_build_and_distinct_full_teams(self):
        core = ('佩可莉姆', '可可萝', '凯露')
        ready = {n: ready_character(n) for n in core}
        others = [f'合成伙伴{i}' for i in range(12)]
        ready.update({n: ready_character(n, level=350, stars=5, skill_level=350) for n in others})
        roles = {n: dict(role=7 if i == 0 else 1, score=50-i, single=1) for i, n in enumerate(others)}
        groups = LabyrinthFormation.plan_boss_parties(ready, roles, strategy=synthetic_boss_strategy())
        self.assertEqual(list(map(len, groups)), [5, 5, 5])
        self.assertEqual(len({n for g in groups for n in g}), 15)
        self.assertEqual(groups[0][:3], list(core))
        with self.assertRaises(EventUIError):
            LabyrinthFormation.plan_boss_parties({n:s for n,s in list(ready.items())[:9]}, roles, strategy=synthetic_boss_strategy())
        with self.assertRaises(EventUIError):
            LabyrinthFormation.require_boss_build(CharacterStatus('未知伙伴', level=350, rank=38,
                                                                  stars=5, skill_level=None))

    def test_verified_strategy_preserves_exact_parties_instead_of_generic_role_scores(self):
        core = ('佩可莉姆', '可可萝', '凯露')
        names = core+('合成魔法破防', '合成魔法辅助', '合成物理辅助', '合成挑衅坦克',
                      '合成物理输出1', '合成物理输出2', '合成物理输出3', '合成物理输出4')
        ready = {n: ready_character(n, stars=6 if n in core else 5) for n in names}
        roles = {n: dict(kind=1, damage=2, role=1, score=100, single=2) for n in names[3:]}
        roles['合成魔法破防'].update(kind=2, role=4, description='降低敌方魔防，提升我方魔法攻击力')
        roles['合成魔法辅助'].update(kind=2, role=5, description='提升我方魔法攻击力并回复技能值')
        roles['合成物理辅助'].update(kind=2, role=5, description='提升物理攻击力和物理攻击力')
        roles['合成挑衅坦克'].update(role=7, tank=True, damage=0, score=0)
        strategy = synthetic_boss_strategy([list(core)+['合成魔法破防', '合成魔法辅助'],
                                            ['合成挑衅坦克', '合成物理输出1', '合成物理输出2', '合成物理输出3', '合成物理辅助']])
        groups = LabyrinthFormation.plan_boss_parties(ready, roles, strategy=strategy)
        self.assertEqual(set(groups[0][3:]), {'合成魔法破防', '合成魔法辅助'})
        self.assertIn('合成挑衅坦克', groups[1])
        self.assertNotIn('合成物理辅助', groups[0])
        self.assertEqual(len({n for g in groups for n in g}), 10)
        self.assertEqual(groups[2], [])
        roles.clear()
        self.assertEqual(LabyrinthFormation.plan_boss_parties(ready, roles, strategy=strategy), groups)

    def test_public_roles_exclude_same_named_npc_units(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'synthetic.db'
            with closing(sqlite3.connect(path)) as db:
                db.executescript('''
                    CREATE TABLE unit_profile(unit_id INTEGER);
                    CREATE TABLE unit_role_data(unit_id INTEGER,unit_role_id INTEGER);
                    CREATE TABLE unit_data(unit_id INTEGER,unit_name TEXT,atk_type INTEGER,search_area_width INTEGER);
                    CREATE TABLE unit_skill_data(unit_id INTEGER,union_burst INTEGER,main_skill_1 INTEGER,main_skill_2 INTEGER);
                    CREATE TABLE skill_data(skill_id INTEGER,description TEXT);
                    INSERT INTO unit_profile VALUES (1);
                    INSERT INTO unit_role_data VALUES (1,7);
                    INSERT INTO unit_data VALUES (1,'合成坦克',1,150),(2,'合成坦克',2,800);
                    INSERT INTO unit_skill_data VALUES (1,101,0,0),(2,102,0,0);
                    INSERT INTO skill_data VALUES (101,'对一名敌人造成物理伤害'),(102,'造成魔法伤害');
                ''')
            roles = character_roles(path)
            self.assertEqual(roles['合成坦克']['role'], 7)
            self.assertEqual(roles['合成坦克']['kind'], 1)

    def test_boss_requires_all_observed_mechanics_and_effects(self):
        description = boss_description()
        effects = '坦克型物防下降魔防下降'
        self.assertTrue(maze.supported_boss('暗黑滴水嘴兽', 350, 60000000, effects, description))
        for change in ({'level': 351}, {'maximum_hp': 60000001}, {'effects': '物防下降'},
                       {'description': description.replace('魔法固定伤害', '')},
                       {'description': description+'物理伤害免疫'}):
            fields = dict(name='暗黑滴水嘴兽', level=350, maximum_hp=60000000, effects=effects, description=description)
            self.assertFalse(maze.supported_boss(**dict(fields, **change)))

    def test_boss_extra_damage_control_or_targeting_clauses_are_rejected(self):
        for extra in ('·对后方一名敌人造成物理伤害', '·降低敌方全体行动速度',
                      '·优先攻击生命值最低的一名敌人', '【技能2】·对前方一名敌人造成魔法固定伤害'):
            with self.subTest(extra=extra):
                self.assertFalse(maze.supported_boss('暗黑滴水嘴兽', 350, 60000000,
                                                    '坦克型物防下降魔防下降', boss_description()+extra))

    def test_boss_profile_rejects_missing_reordered_or_repeated_known_clauses(self):
        clause = '·对进行魔法攻击的敌方全体赋予烧伤状态'
        for description in ('', boss_description().replace(clause, ''),
                            boss_description()+clause,
                            boss_description().replace('·降低敌方全体生命值吸收量【技能1】',
                                                       '【技能1】·降低敌方全体生命值吸收量'),
                            boss_description().replace('·对敌方全体造成魔法伤害·击退敌方全体（必中）',
                                                       '·击退敌方全体（必中）·对敌方全体造成魔法伤害')):
            with self.subTest(description=description):
                self.assertFalse(maze.supported_boss('暗黑滴水嘴兽', 350, 60000000,
                                                    '坦克型物防下降魔防下降', description))

    def test_normal_enemy_unknown_preamble_and_changed_category_are_rejected(self):
        description = normal_enemy_detail().items[-2].text
        prefix, clauses = description.split('·', 1)
        for changed in ('', '【物理】优先攻击后排。', prefix+'优先攻击后排。',
                        prefix.replace('【防御】', '【范围】')):
            with self.subTest(prefix=changed):
                self.assertFalse(maze.supported_normal_enemy(700000, changed+'·'+clauses, name='雪原山羊'))

    def test_boss_unknown_preamble_is_rejected_before_reconstruction(self):
        for prefix in ('【物理】优先攻击后排。', boss_intro()+'降低敌方全体行动速度。',
                       boss_intro()+'物防下降'):
            with self.subTest(prefix=prefix):
                description = prefix+boss_description()
                self.assertFalse(maze.known_boss_description_part(description))
                self.assertIsNone(maze.merge_boss_descriptions([description]))
                self.assertFalse(maze.supported_boss('暗黑滴水嘴兽', 350, 60000000,
                                                     '坦克型物防下降魔防下降', description))

    def test_every_enemy_info_button_is_found_when_one_level_is_unreadable(self):
        value = screen(('战斗格子（普通）', 138, 56), ('挑战', 817, 457), ('Lv.380', 350, 320))
        for x in (176, 401, 626, 851):
            cv.circle(value.image, (x, 316), 14, (230, 230, 230), -1)
            cv.rectangle(value.image, (x-2, 306), (x+1, 309), (230, 120, 100), -1)
            cv.rectangle(value.image, (x-2, 313), (x+1, 325), (230, 120, 100), -1)
        self.assertEqual(len(maze.enemy_information(value)), 4)
        self.assertEqual([p[0] for p in maze.enemy_information(value)], [176, 400, 626, 850])
        value.image[:] = 0
        self.assertEqual(maze.enemy_information(value), [])

    def test_normal_enemy_requires_a_known_identity_and_complete_skill_profile(self):
        description = '【物理】【防御】住在高山上,厚实的毛皮之下拥有强韧的身体,驯鹿魔物。·近身攻击·造成伤害所获得的技能值回复量降低80%'
        self.assertTrue(maze.supported_normal_enemy(2200000, description, name='雪原山羊'))
        self.assertFalse(maze.supported_normal_enemy(3100000, description, name='雪原山羊'))
        self.assertFalse(maze.supported_normal_enemy(700000, description, name='合成未知魔物'))
        self.assertFalse(maze.supported_normal_enemy(700000, description))
        for text in (description+'·降低敌方防御力', description.replace('80%', '8'),
                     description.replace('·近身攻击', ''), description+'·造成比例伤害'):
            with self.subTest(text=text):
                self.assertFalse(maze.supported_normal_enemy(700000, text, name='雪原山羊'))

    def test_empty_or_partial_normal_enemy_description_is_not_supported(self):
        for description in ('', ' ', '【物理】', '近身攻击', '·近身攻击',
                            '·造成伤害所获得的技能值回复量降低80%'):
            with self.subTest(description=description):
                self.assertFalse(maze.supported_normal_enemy(700000, description))

    def test_knockback_through_immunity_is_not_enemy_damage_immunity(self):
        description = ('【物理】【干扰】模仿大人敲打乐器,喜欢恶作剧的兽人孩童。·近身攻击、击退（在伤害免疫的情况下也会成功赋予）'
                       '·造成伤害所获得的技能值回复量降低80%')
        self.assertTrue(maze.supported_normal_enemy(700000, description, name='快乐兽人'))
        self.assertFalse(maze.supported_normal_enemy(700000, description+'·魔物自身拥有伤害免疫', name='快乐兽人'))

    def test_event_requires_explicit_free_rewards_and_rejects_costs(self):
        value = screen(('触发事件！', 480, 40), ('这里是公会管理协会', 480, 88),
                       ('随机印记×2', 340, 385), ('+阿尔法金币×200', 340, 400),
                       ('选择', 340, 445), blue=('选择',))
        self.assertIsNotNone(maze.free_event_choice(value))
        value.items.extend(screen(('消耗阿尔法金币', 480, 300)).items)
        self.assertIsNone(maze.free_event_choice(value))

    def test_relic_effect_must_be_entirely_positive_and_readable(self):
        value = screen(('获得道具的机会！', 480, 50), ('请选择要获得的迷宫遗物。', 480, 92),
                       ('还剩1次', 480, 122), ('物理/魔法攻击力+20%', 202, 392),
                       ('HP+10%', 480, 392), ('选择', 202, 464), ('选择', 480, 464), blue=('选择',))
        self.assertEqual(maze.positive_relic_choice(value).center[0], 480)
        value.items[4].text = 'HP-10%'
        self.assertEqual(maze.positive_relic_choice(value).center[0], 202)
        value.items[3].score = .94
        self.assertIsNone(maze.positive_relic_choice(value))

    def test_difficulty_requires_one_selected_radio(self):
        self.assertEqual(maze.selected_difficulty(difficulty()), 1)
        self.assertEqual(maze.selected_difficulty(difficulty(2)), 2)
        ambiguous = difficulty()
        cv.rectangle(ambiguous.image, (274, 245), (291, 262), (230, 155, 25), -1)
        self.assertIsNone(maze.selected_difficulty(ambiguous))

    def test_flat_lifesteal_relic_requires_enabled_choice_and_positive_amount(self):
        value = screen(('获得道具的机会！', 480, 50), ('请选择要获得的迷宫遗物。', 480, 92),
                       ('还剩1次', 480, 122), ('生命值吸收+10', 202, 392),
                       ('选择', 202, 464), blue=('选择',))
        self.assertEqual(maze.positive_relic_choice(value).center[0], 202)
        value.items[3].text = '生命值吸收-10'
        self.assertIsNone(maze.positive_relic_choice(value))
        value.items[3].text = '生命值吸收+10'
        value.image[:] = 0
        self.assertIsNone(maze.positive_relic_choice(value))

    def test_tp_relic_accepts_only_a_single_unconditional_positive_effect(self):
        value = screen(('获得道具的机会！', 480, 50), ('请选择要获得的迷宫遗物。', 480, 92),
                       ('还剩1次', 480, 122), ('技能值上升量+10', 202, 392),
                       ('战斗开始时技能值回复100', 480, 392),
                       ('选择', 202, 464), ('选择', 480, 464), blue=('选择',))
        self.assertEqual(maze.positive_relic_choice(value).center[0], 202)
        value.items[3].text = '技能值上升量-10'
        self.assertEqual(maze.positive_relic_choice(value).center[0], 480)
        value.items.extend(screen(('消耗金币100', 480, 410)).items)
        self.assertIsNone(maze.positive_relic_choice(value))

    def test_departure_requires_one_pass_and_verified_guild(self):
        ui = Mock()
        ui.number.side_effect = lambda s, roi: s.number(roi)
        self.assertEqual(maze.departure_preview(ui, departure()), (11, 10))
        for value in (departure(0, 0), departure(11, 9), departure(11, 11)):
            with self.assertRaises(EventUIError):
                maze.departure_preview(ui, value)
        value = departure()
        value.items[1].text = '将消耗1张迷宫通行证和【其他公会】一同出发。'
        with self.assertRaises(EventUIError):
            maze.departure_preview(ui, value)

    def test_unknown_identity_or_underleveled_partner_blocks_trial(self):
        valid = vars(ready_character('合成伙伴'))
        LabyrinthFormation.require_build(CharacterStatus(**valid), 360)
        for change in ({'identity_verified': False}, {'level': None}, {'level': 359},
                       {'rank': None}, {'stars': 5}, {'skill_level': None}):
            with self.subTest(change=change), self.assertRaises(EventUIError):
                LabyrinthFormation.require_build(CharacterStatus(**dict(valid, **change)), 360)

    def test_normal_and_boss_builds_reject_unverified_or_incomplete_equipment(self):
        for check in (LabyrinthFormation.require_build, LabyrinthFormation.require_boss_build):
            for change in ({'equipment': None}, {'equipment': 0}, {'equipment': 5},
                           {'equipment': True}, {'unique': None}, {'unique2': None},
                           {'unique': 1}, {'equipment_evidence': ''},
                           {'unique': False, 'unique2': True}):
                with self.subTest(check=check.__name__, change=change), self.assertRaisesRegex(EventUIError, '装备'):
                    check(ready_character('合成伙伴', **change))
            for unique, unique2 in ((False, False), (True, False), (True, True)):
                check(ready_character('合成伙伴', unique=unique, unique2=unique2))

    def test_all_released_slots_can_be_four_without_inventing_future_equipment(self):
        for check in (LabyrinthFormation.require_build, LabyrinthFormation.require_boss_build):
            value = ready_character('合成伙伴', equipment=4, equipment_available=4,
                                    ordinary_equipment_evidence=['synthetic-six-slot-audit'])
            check(value)
            for change in ({'equipment': 3}, {'equipment_available': 6},
                           {'equipment_available': True}, {'ordinary_equipment_evidence': []}):
                with self.subTest(change=change), self.assertRaisesRegex(EventUIError, '装备'):
                    check(replace(value, **change))

    def test_boss_planner_rechecks_equipment_of_non_core_members(self):
        names = ('佩可莉姆', '可可萝', '凯露')+tuple(f'合成伙伴{i}' for i in range(7))
        ready = {name: ready_character(name, stars=6 if name in names[:3] else 5) for name in names}
        ready[names[-1]].unique2 = None
        with self.assertRaisesRegex(EventUIError, '装备'):
            LabyrinthFormation.plan_boss_parties(ready, {}, strategy=synthetic_boss_strategy([list(names[:5]), list(names[5:])]))

    def test_invitation_animation_is_not_a_character_selection_button(self):
        self.assertTrue(maze.invitation_animation(screen(('合成伙伴', 790, 435))))
        self.assertFalse(maze.invitation_animation(screen(('合成伙伴', 790, 435), ('选择', 790, 490), ('角色选择', 480, 42))))


class LabyrinthFormationTests(TestCase):
    def test_only_same_owned_build_recruited_this_run_uses_predeparture_equipment(self):
        formation = object.__new__(LabyrinthFormation)
        formation.departure_verified_at = 2000
        formation.departure_equipment = {'合成伙伴': dict(level=365, rank=38, observed_at=1900,
            values=dict(equipment=4, equipment_available=4, unique=True, unique2=False),
            ordinary_evidence=['synthetic-slots'], unique_evidence=['synthetic-unique'])}
        value = ready_character('合成伙伴', equipment=None)
        formation.bind_departure_equipment(value)
        self.assertEqual((value.equipment, value.equipment_available), (4, 4))
        self.assertEqual(value.ordinary_equipment_evidence, ['synthetic-slots'])
        for change in ({'level': 320, 'rank': 34}, {'level': 364}, {'rank': 37}, {'identity_verified': False}):
            value = ready_character('合成伙伴', equipment=None, **change)
            formation.bind_departure_equipment(value)
            self.assertIsNone(value.equipment)
        formation.departure_verified_at = None
        value = ready_character('合成伙伴', equipment=None)
        formation.bind_departure_equipment(value)
        self.assertIsNone(value.equipment)

    def test_expired_future_or_conflicting_predeparture_equipment_cannot_be_bound(self):
        formation = object.__new__(LabyrinthFormation)
        formation.departure_verified_at = 2000
        proof = dict(level=365, rank=38, observed_at=100,
            values=dict(equipment=4, equipment_available=4, unique=True, unique2=False),
            ordinary_evidence=['synthetic-slots'], unique_evidence=['synthetic-unique'])
        formation.departure_equipment = {'合成伙伴': proof}
        for observed in (100, 2001):
            proof['observed_at'] = observed
            value = ready_character('合成伙伴', equipment=None)
            formation.bind_departure_equipment(value)
            self.assertIsNone(value.equipment)
        proof['observed_at'] = 1900
        with self.assertRaisesRegex(EventUIError, '不符'):
            formation.bind_departure_equipment(ready_character('合成伙伴', equipment=None, unique=False))
    def test_neighboring_rows_recover_a_card_with_an_interrupted_border(self):
        value = screen(('队伍编组', 480, 42))
        cv.rectangle(value.image, (178, 281), (254, 348), (230, 155, 25), -1)
        with patch('pcrscript.tasks.dawn_labyrinth_party.card_rectangles', return_value=[(272, 266, 99, 99)]):
            rectangles = LabyrinthFormation.visible_cards(value)
        self.assertIn((166, 266, 100, 99), rectangles)
        self.assertIn((272, 266, 99, 99), rectangles)
        self.assertEqual(len(rectangles), 2)

    def test_roster_scroll_stops_as_soon_as_a_detail_dialog_appears(self):
        formation = object.__new__(LabyrinthFormation)
        formation.ui = Mock(capture=Mock(return_value=screen(('角色详情', 480, 42))))
        with self.assertRaises(EventUIError):
            formation.scroll_to_start()
        self.assertEqual(formation.ui.swipe.call_count, 1)

    def test_selected_count_uses_requested_members_not_all_visible_candidates(self):
        value = screen(('队伍编组', 480, 42))
        formation = object.__new__(LabyrinthFormation)
        formation.ui = Mock(capture=Mock(return_value=value))
        core = ('佩可莉姆', '可可萝', '凯露')
        formation.avatars = Mock(query=Mock(return_value=list(core)+['合成储备'+str(i) for i in range(5)]))
        formation.observed = {}
        formation.clear_current = Mock(return_value=value)
        formation.occupied_slots = Mock(return_value=[(96, 452), (205, 452), (314, 452)])
        formation.inspect = Mock(side_effect=lambda pos, **kwargs: ready_character(kwargs['expected_name']))
        rectangles = [(60+106*i, 177, 100, 99) for i in range(8)]
        with patch('pcrscript.tasks.dawn_labyrinth_party.card_rectangles', return_value=rectangles):
            party, result = formation.select_standard(360)
            self.assertEqual([member['name'] for member in party], list(core))
            self.assertIs(result, value)
            self.assertEqual(formation.ui.click.call_count, 3)
            formation.occupied_slots.return_value.pop()
            with self.assertRaises(EventUIError):
                formation.select_standard(360)

    def test_unknown_equipment_is_rejected_before_member_selection(self):
        for boss in (False, True):
            with self.subTest(boss=boss):
                formation = object.__new__(LabyrinthFormation)
                value = screen(('队伍编组', 480, 42))
                formation.ui = Mock(capture=Mock(return_value=value))
                formation.clear_current = Mock(return_value=value)
                formation.visible_cards = Mock(return_value=[(60, 177, 100, 99)])
                formation.avatars = Mock(query=Mock(return_value=['合成伙伴']))
                formation.observed = {}
                formation.inspect = Mock(return_value=ready_character('合成伙伴', equipment=None))
                with self.assertRaisesRegex(EventUIError, '装备'):
                    formation.select_members(('合成伙伴',), 350, boss=boss)
                formation.ui.click.assert_not_called()

    def test_inspection_observes_badges_without_inventing_ordinary_equipment_count(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        formation = object.__new__(LabyrinthFormation)
        detail = screen(('角色详情', 480, 42), ('合成伙伴', 610, 80),
                        ('365', 555, 115), ('38', 790, 115), ('关闭', 480, 480))
        formation.ui = Mock(output=Path(folder.name), capture=Mock(return_value=screen()),
                            wait=Mock(return_value=detail),
                            save=Mock(return_value=Path('synthetic.png')))
        formation.avatars = Mock(query=Mock(return_value=['合成伙伴']))
        formation.badges = Mock(observe=Mock(return_value=((True, False), detail)))
        formation.observed = {}
        value = formation.inspect((110, 220), rectangle=(60, 177, 100, 99),
                                  expected_name='合成伙伴', verify_skills=False)
        formation.badges.observe.assert_called_once_with(formation.ui, (60, 177, 100, 99))
        self.assertEqual((value.unique, value.unique2), (True, False))
        self.assertTrue(value.equipment_evidence)
        self.assertIsNone(value.equipment)
        with self.assertRaisesRegex(EventUIError, '装备'):
            formation.require_build(value)


class FirstClearTaskTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.robot = Robot(Mock(get_screen_size=Mock(return_value=(960, 540))), show_progress=False)
        self.robot.configure({'DawnLabyrinthFirstClear': {'output': str(self.folder)},
                              'DawnLabyrinth': {'output': str(self.folder/'daily'),
                                               'state_dir': str(self.folder/'state'),
                                               'account_key': 'synthetic-account'}})
        self.task = DawnLabyrinthFirstClear(self.robot)
        self.task.ui = Mock(output=self.folder, last=None)
        self.task.ui.save.return_value = self.folder/'synthetic.png'
        self.task.ui.number.side_effect = lambda s, roi: s.number(roi)
        self.core_preparation = patch.object(self.task, 'prepare_core_equipment', side_effect=lambda s, before: s)
        self.core_preparation.start()
        self.addCleanup(self.core_preparation.stop)
        self.sleep = patch('pcrscript.tasks.task_dawn_labyrinth_first_clear.time.sleep')
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.temp.cleanup()

    def frames(self, values):
        iterator = iter(values)
        def capture():
            value = next(iterator, values[-1])
            self.task.ui.last = value
            return value
        self.task.ui.capture.side_effect = capture

    def clicks(self):
        return [getattr(call.args[0], 'text', call.args[0]) for call in self.task.ui.click.call_args_list]

    def core_proof(self, level=365, observed_at=1000):
        return dict(level=level, rank=38, observed_at=observed_at,
                    values=dict(equipment=4, equipment_available=4), evidence=['synthetic-slots'])

    def test_core_cultivation_gap_is_reported_before_any_departure_spend(self):
        with patch.object(self.task, 'get_formation', return_value=Mock()), \
                patch.object(self.task, 'wait', return_value=home(11)), \
                patch('pcrscript.tasks.task_home.ToHomePage') as to_home, \
                patch('pcrscript.game_ui.ordinary_equipment.inspect_ordinary_equipment',
                      return_value=self.core_proof(level=355)), \
                patch('pcrscript.game_ui.character_equipment.inspect_unique_equipment') as unique:
            with self.assertRaisesRegex(EventUIError,'等级365'):
                DawnLabyrinthFirstClear.prepare_core_equipment(self.task, self.guild(), 11)
        unique.assert_not_called()
        self.assertEqual(to_home.return_value.run.call_count,2)
        self.assertEqual(self.task.report['core_equipment']['佩可莉姆']['level'],355)
        self.assertEqual((self.task.report['entries'],self.task.report['spent']), (0,0))
        self.assertNotIn('pending_spend',self.task.report)
        self.assertEqual(self.clicks(),[(30,30)])

    def test_unknown_independent_unique_slot_blocks_before_departure(self):
        with patch.object(self.task, 'get_formation', return_value=Mock()), \
                patch.object(self.task, 'wait', return_value=home(11)), \
                patch('pcrscript.tasks.task_home.ToHomePage'), \
                patch('pcrscript.game_ui.ordinary_equipment.inspect_ordinary_equipment',
                      return_value=self.core_proof()), \
                patch('pcrscript.game_ui.character_equipment.inspect_unique_equipment',
                      return_value=dict(values=dict(unique=True,unique2=None))):
            with self.assertRaisesRegex(EventUIError,'独立专武'):
                DawnLabyrinthFirstClear.prepare_core_equipment(self.task,self.guild(),11)
        self.assertNotIn('pending_spend',self.task.report)
        self.assertEqual(self.clicks(),[(30,30)])

    def test_core_check_cancellation_does_not_issue_cleanup_navigation(self):
        with patch.object(self.task, 'get_formation', return_value=Mock()), \
                patch.object(self.task, 'wait', return_value=home(11)), \
                patch('pcrscript.tasks.task_home.ToHomePage') as to_home, \
                patch('pcrscript.game_ui.ordinary_equipment.inspect_ordinary_equipment',side_effect=RunCancelled):
            with self.assertRaises(RunCancelled):
                DawnLabyrinthFirstClear.prepare_core_equipment(self.task,self.guild(),11)
        self.assertEqual(to_home.return_value.run.call_count,1)
        self.assertEqual(self.clicks(),[(30,30)])

    def test_all_core_checks_recheck_balance_and_unlock_before_authorizing_entry(self):
        formation = Mock()
        target = self.guild()
        with patch.object(self.task,'get_formation',return_value=formation), \
                patch.object(self.task,'wait',side_effect=[home(11),target]), \
                patch.object(self.task,'enter',return_value=home(11)), \
                patch.object(self.task,'difficulty_one',return_value=target), \
                patch.object(self.task,'check_unlock',return_value=target) as unlock, \
                patch('pcrscript.tasks.task_home.ToHomePage'), \
                patch('pcrscript.game_ui.ordinary_equipment.inspect_ordinary_equipment',
                      side_effect=lambda ui,name,**kwargs: self.core_proof()), \
                patch('pcrscript.game_ui.character_equipment.inspect_unique_equipment',
                      return_value=dict(values=dict(unique=True,unique2=False),evidence=['synthetic-unique'])), \
                patch('pcrscript.tasks.task_dawn_labyrinth_first_clear.time.time',return_value=1001):
            self.assertIs(DawnLabyrinthFirstClear.prepare_core_equipment(self.task,target,11),target)
        self.assertEqual(set(formation.departure_equipment),{'佩可莉姆','可可萝','凯露'})
        unlock.assert_called_once_with(target)
        self.assertNotIn('pending_spend',self.task.report)

    def test_expired_core_equipment_stops_before_reopening_entry(self):
        with patch.object(self.task,'get_formation',return_value=Mock()), \
                patch.object(self.task,'wait',return_value=home(11)), \
                patch.object(self.task,'enter') as enter, \
                patch('pcrscript.tasks.task_home.ToHomePage'), \
                patch('pcrscript.game_ui.ordinary_equipment.inspect_ordinary_equipment',
                      side_effect=lambda ui,name,**kwargs: self.core_proof(observed_at=0)), \
                patch('pcrscript.game_ui.character_equipment.inspect_unique_equipment',
                      return_value=dict(values=dict(unique=True,unique2=False),evidence=['synthetic-unique'])), \
                patch('pcrscript.tasks.task_dawn_labyrinth_first_clear.time.time',return_value=2000):
            with self.assertRaisesRegex(EventUIError,'已过期'):
                DawnLabyrinthFirstClear.prepare_core_equipment(self.task,self.guild(),11)
        enter.assert_not_called()
        self.assertNotIn('pending_spend',self.task.report)

    def test_daily_pending_blocks_first_clear_without_altering_daily_state(self):
        for pending in ({'pending_spend': dict(before=1, after=0, cost=1)},
                        {'pending_mission_claim': dict(preview='synthetic.png')}):
            with self.subTest(pending=pending):
                daily = DawnLabyrinth(self.robot)
                daily.report.update(pending)
                daily.save_report()
                self.task = DawnLabyrinthFirstClear(self.robot)
                self.task.ui = Mock(output=self.folder, last=None)
                report = self.task.run()
                self.assertEqual(report['status'], 'blocked', report)
                self.task.ui.capture.assert_not_called()
                self.task.ui.click.assert_not_called()
                self.assertEqual(json.loads(daily.state_path.read_text(encoding='utf-8')), pending)
                daily.state_path.unlink()

    def test_unknown_normal_enemy_mechanics_stop_before_challenge_or_formation(self):
        stage = screen(('战斗格子（普通）', 138, 56), ('挑战', 817, 457))
        for description in ('', '【物理】合成说明。', '·近身攻击', '·未知效果'):
            with self.subTest(description=description):
                self.task.ui.click.reset_mock()
                self.task.exploration_verified = True
                self.frames([normal_enemy_detail(description), stage,
                             screen(('队伍编组', 480, 42))])
                with patch.object(maze, 'enemy_information', return_value=[(176, 316)]), \
                        patch.object(self.task, 'get_formation', side_effect=EventUIError('未在战前拦截')) as formation:
                    with self.assertRaises(EventUIError):
                        self.task.fight(stage)
                self.assertNotIn('挑战', self.clicks())
                formation.assert_not_called()
                self.assertNotIn('pending_battle', self.task.report)

    def test_normal_enemy_hidden_or_low_confidence_content_stops_before_challenge(self):
        stage = screen(('战斗格子（普通）', 138, 56), ('挑战', 817, 457))
        low = normal_enemy_detail()
        low.items[-2].score = .94
        hidden = normal_enemy_detail('·造成比例伤害')
        unreadable_tail = normal_enemy_detail()
        unreadable_tail.image[330:345, 300:650] = 0
        footer = normal_enemy_detail()
        footer.items.extend(screen(('·未知效果', 480, 438)).items)
        changed_identity = normal_enemy_detail()
        changed_identity.items[1].text = '合成未知魔物'
        for initial, tail in ((low, low), (normal_enemy_detail(), hidden),
                              (normal_enemy_detail(), unreadable_tail), (footer, footer),
                              (normal_enemy_detail(), changed_identity)):
            with self.subTest(initial=initial.text(), tail=tail.text()):
                self.task.ui.click.reset_mock()
                self.task.exploration_verified = True
                self.frames([initial, tail, stage, screen(('队伍编组', 480, 42))])
                with patch.object(maze, 'enemy_information', return_value=[(176, 316)]), \
                        patch.object(self.task, 'get_formation', side_effect=EventUIError('未在战前拦截')) as formation:
                    with self.assertRaises(EventUIError):
                        self.task.fight(stage)
                self.assertNotIn('挑战', self.clicks())
                formation.assert_not_called()

    def test_unknown_enemy_preambles_stop_before_challenge(self):
        normal = normal_enemy_detail().items[-2].text.split('·', 1)[1]
        cases = (
            ('战斗格子（普通）', normal_enemy_detail('【物理】优先攻击后排。·'+normal)),
            ('首领战格子', boss_enemy_detail('【物理】优先攻击后排。'+boss_description())),
        )
        for label, detail in cases:
            with self.subTest(stage=label):
                self.task.ui.click.reset_mock()
                self.task.exploration_verified = True
                stage = screen((label, 138, 56), ('挑战', 817, 457))
                self.frames([detail, detail, stage, screen(('队伍编组', 480, 42))])
                with patch.object(maze, 'enemy_information', return_value=[(176, 316)]), \
                        patch.object(self.task, 'get_formation', side_effect=EventUIError('未在战前拦截')) as formation:
                    with self.assertRaises(EventUIError):
                        self.task.fight(stage)
                self.assertNotIn('挑战', self.clicks())
                formation.assert_not_called()
                self.assertNotIn('pending_battle', self.task.report)

    def test_missing_boss_intro_cannot_authorize_a_battle(self):
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457))
        detail = boss_enemy_detail()
        self.frames([detail, detail, stage, screen(('队伍编组', 480, 42))])
        self.task.exploration_verified = True
        with patch.object(maze, 'enemy_information', return_value=[(176, 316)]), \
                patch.object(self.task, 'get_formation', side_effect=EventUIError('未在战前拦截')) as formation:
            with self.assertRaises(EventUIError):
                self.task.fight(stage)
        self.assertNotIn('挑战', self.clicks())
        formation.assert_not_called()

    def test_unknown_boss_clauses_stop_before_challenge_and_saved_team_changes(self):
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457))
        for extra in ('·对后方一名敌人造成物理伤害', '·降低敌方全体行动速度'):
            with self.subTest(extra=extra):
                self.task.ui.click.reset_mock()
                self.task.exploration_verified = True
                detail = boss_enemy_detail(boss_description()+extra)
                self.frames([detail, detail, stage, screen(('队伍编组', 480, 42))])
                with patch.object(maze, 'enemy_information', return_value=[(176, 316)]), \
                        patch.object(self.task, 'get_formation', side_effect=EventUIError('未在战前拦截')) as formation:
                    with self.assertRaises(EventUIError):
                        self.task.fight(stage)
                self.assertNotIn('挑战', self.clicks())
                formation.assert_not_called()
                self.assertNotIn('pending_battle', self.task.report)

    def test_complete_boss_profile_is_read_across_overlap_without_starting_combat(self):
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457))
        initial = boss_enemy_detail(boss_intro()+'【特殊效果】·所有的技能伤害无法回复技能值'
                                    '【必杀技能】·对进行物理攻击的敌方全体赋予烧伤状态')
        final = boss_enemy_detail()
        self.frames([initial, final, final, stage])
        with patch.object(maze, 'enemy_information', return_value=[(176, 316)]):
            enemies, returned = self.task.inspect_enemies(stage)
        self.assertIs(returned, stage)
        self.assertEqual(enemies[0]['name'], '暗黑滴水嘴兽')
        self.assertEqual(self.clicks(), [(176, 316), '关闭'])
        self.assertEqual(self.task.ui.swipe.call_count, 2)

    def test_boss_profile_is_reconstructed_when_final_page_contains_only_the_tail(self):
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457))
        full = boss_description()
        first = boss_enemy_detail(boss_intro()+full[:full.index('·降低敌方全体生命值吸收量')])
        last = boss_enemy_detail(full[full.index('·对进行魔法攻击的敌方全体赋予烧伤状态'):])
        self.frames([first, last, last, stage])
        with patch.object(maze, 'enemy_information', return_value=[(176, 316)]):
            enemies, returned = self.task.inspect_enemies(stage)
        self.assertIs(returned, stage)
        self.assertTrue(maze.supported_boss('暗黑滴水嘴兽', 350, 60000000,
                                            '坦克型物防下降魔防下降', enemies[0]['description']))
        self.assertEqual(len(enemies[0]['description_evidence']), 2)
        self.assertEqual(self.clicks(), [(176, 316), '关闭'])
        self.assertEqual(self.task.ui.swipe.call_count, 2)

    def test_boss_profile_joins_three_overlapping_pages_with_clipped_last_bullets(self):
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457))
        full = boss_description()
        first = boss_intro()+full[:full.index('·对进行魔法攻击的敌方全体赋予烧伤状态')]
        first += '·对进行魔法攻击的敌方全体赋予烧'
        middle = full[full.index('·自身的物理防御力越高'):full.index('【技能1】')]
        middle += '【技能1】·对敌方全体造成魔法'
        last = full[full.index('·自身的魔法防御力越高'):]
        pages = [boss_enemy_detail(part) for part in (first, middle, last)]
        self.frames([*pages, pages[-1], stage])
        with patch.object(maze, 'enemy_information', return_value=[(176, 316)]):
            enemies, returned = self.task.inspect_enemies(stage)
        self.assertIs(returned, stage)
        self.assertTrue(maze.supported_boss('暗黑滴水嘴兽', 350, 60000000,
                                            '坦克型物防下降魔防下降', enemies[0]['description']))
        self.assertEqual(len(enemies[0]['description_evidence']), 3)
        self.assertEqual(self.clicks(), [(176, 316), '关闭'])
        self.assertEqual(self.task.ui.swipe.call_count, 3)

    def test_boss_disconnected_reordered_or_unknown_scroll_pages_stop_before_challenge(self):
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457))
        full = boss_description()
        first = boss_intro()+full[:full.index('·降低敌方全体生命值吸收量')]
        tail = full[full.index('·对进行魔法攻击的敌方全体赋予烧伤状态'):]
        scenarios = (
            (boss_intro()+full[:full.index('·对进行魔法攻击的敌方全体赋予烧伤状态')], tail),
            (first, tail, first),
            (first, tail+'·降低敌方全体行动速度'),
            (first, '降低敌方全体行动速度'+tail),
            (boss_intro()+full[:full.index('【技能1】')]+'【技能1】·对敌方全体造成魔法',
             full[full.index('·对敌方全体造成魔法伤害'):]),
            (first, tail.replace('·降低敌方全体生命值吸收量【技能1】',
                                 '【技能1】·降低敌方全体生命值吸收量')),
        )
        for descriptions in scenarios:
            with self.subTest(descriptions=descriptions):
                self.task.ui.click.reset_mock()
                self.task.exploration_verified = True
                pages = [boss_enemy_detail(part) for part in descriptions]
                self.frames([*pages, pages[-1], stage, screen(('队伍编组', 480, 42))])
                with patch.object(maze, 'enemy_information', return_value=[(176, 316)]), \
                        patch.object(self.task, 'get_formation', side_effect=EventUIError('未在战前拦截')) as formation:
                    with self.assertRaises(EventUIError):
                        self.task.fight(stage)
                self.assertNotIn('挑战', self.clicks())
                formation.assert_not_called()
                self.assertNotIn('pending_battle', self.task.report)

    def test_extra_boss_clause_on_an_earlier_page_cannot_be_discarded(self):
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457))
        initial = boss_enemy_detail('【特殊效果】·对后方一名敌人造成物理伤害')
        final = boss_enemy_detail()
        self.frames([initial, final, final, stage, screen(('队伍编组', 480, 42))])
        self.task.exploration_verified = True
        with patch.object(maze, 'enemy_information', return_value=[(176, 316)]), \
                patch.object(self.task, 'get_formation', side_effect=EventUIError('未在战前拦截')) as formation:
            with self.assertRaises(EventUIError):
                self.task.fight(stage)
        self.assertNotIn('挑战', self.clicks())
        formation.assert_not_called()

    def test_complete_known_normal_enemy_is_read_without_starting_combat(self):
        stage = screen(('战斗格子（普通）', 138, 56), ('挑战', 817, 457))
        detail = normal_enemy_detail()
        self.frames([detail, detail, stage])
        with patch.object(maze, 'enemy_information', return_value=[(176, 316)]):
            enemies, returned = self.task.inspect_enemies(stage)
        self.assertIs(returned, stage)
        self.assertEqual(enemies[0]['name'], '雪原山羊')
        self.assertEqual(self.clicks(), [(176, 316), '关闭'])
        self.task.ui.swipe.assert_called_once()

    def guild(self):
        value = guild(('难度变更', 843, 65), ('美食殿堂', 144, 352))
        cv.rectangle(value.image, (94, 398), (194, 446), (230, 155, 25), -1)
        return value

    def locked(self):
        value = self.guild()
        value.items.extend(screen(('通关1次难度1后可解锁。', 480, 267)).items)
        return value

    def test_zero_passes_without_first_clear_never_starts_an_entry(self):
        self.frames([home(0), home(0), self.guild(), difficulty(), self.guild(), self.locked(), self.guild()])
        self.assertEqual(self.task.run()['status'], 'blocked')
        self.assertNotIn('选择', self.clicks())
        self.assertEqual(self.task.report['entries'], 0)
        self.assertNotIn('pending_spend', self.task.report)

    def test_zero_pass_departure_preview_is_cancelled_before_returning_home(self):
        expected = home(0)
        self.frames([zero_departure(), self.guild(), expected])
        self.assertIs(self.task.enter(), expected)
        self.assertEqual(self.clicks(), ['取消', (30, 30)])
        self.assertEqual(self.task.report['entries'], 0)
        self.assertNotIn('pending_spend', self.task.report)

    def test_zero_passes_already_cleared_catalogue_completes_without_spending(self):
        self.frames([home(0), home(0), self.guild(), difficulty(), self.guild(),
                     catalogue(0, selected=False), self.guild(), home(0)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertEqual((report['spent'], report['entries'], report['remaining_passes']), (0, 0, 0))
        self.assertNotIn('一键扫荡', self.clicks())
        self.assertNotIn('选择', self.clicks())

    def test_target_guild_unlock_proof_completes_each_layout_without_consuming(self):
        for value in (catalogue(0, selected=False), cleared_preview(0, 0),
                      sweep_guild_choice(), bulk(guild_name='美食殿堂')):
            with self.subTest(page=value.text()):
                self.task = DawnLabyrinthFirstClear(self.robot)
                self.task.ui = Mock(output=self.folder, last=None)
                self.task.ui.save.return_value = self.folder/'synthetic.png'
                self.frames([home(0), home(0), self.guild(), difficulty(), self.guild(),
                             value, self.guild(), home(0)])
                report = self.task.run()
                self.assertEqual(report['status'], 'complete')
                self.assertTrue(report['already_cleared'])
                self.assertEqual((report['spent'], report['entries'], report['battles']), (0, 0, 0))
                self.assertNotIn('pending_spend', report)
                self.assertEqual(self.clicks().count('跳过'), 1)
                self.assertEqual(self.clicks().count('出发'), 1)
                self.assertNotIn('选择', self.clicks())
                self.assertNotIn('一键扫荡', self.clicks())
                self.assertNotIn('挑战', self.clicks())

    def test_wrong_or_unknown_unlock_guild_never_completes_or_departures(self):
        wrong_catalogue = catalogue(selected=False)
        wrong_catalogue.items[1].text = '合成公会'
        low_preview = cleared_preview()
        low_preview.items[-1].score = .94
        for value in (wrong_catalogue, cleared_preview(guild_name='合成公会'),
                      cleared_preview(guild_name=None), low_preview,
                      sweep_guild_choice(guild_name='合成公会'), sweep_guild_choice(enabled=False),
                      bulk(guild_name='合成公会')):
            with self.subTest(page=value.text()):
                self.task = DawnLabyrinthFirstClear(self.robot)
                self.task.ui = Mock(output=self.folder, last=None)
                self.task.ui.save.return_value = self.folder/'synthetic.png'
                self.frames([home(11), home(11), self.guild(), difficulty(), self.guild(),
                             value, self.guild(), home(11)])
                with patch.object(self.task, 'collect_mission_rewards') as missions:
                    report = self.task.run()
                self.assertEqual(report['status'], 'blocked')
                self.assertIn('未确认美食殿堂已通关难度1', report['pending'][-1])
                self.assertNotIn('already_cleared', report)
                self.assertNotIn('clear_evidence', report)
                self.assertNotIn('pending_spend', report)
                self.assertEqual((report['spent'], report['entries'], report['battles']), (0, 0, 0))
                self.assertEqual(self.clicks(), ['出发', '难度变更', '取消', '跳过'])
                self.assertIs(self.task.ui.last, value)
                missions.assert_not_called()

    def test_settlement_unlock_for_other_guild_does_not_finalize_pass_spend(self):
        self.task.report.update(entries=1, pending_spend=dict(before=11, after=10, cost=1))
        self.frames([score_result(), home(10), self.guild(), difficulty(), self.guild(),
                     cleared_preview(guild_name='合成公会'), self.guild(), home(10)])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertNotIn('already_cleared', report)
        self.assertEqual(report['spent'], 0)
        self.assertEqual(report['pending_spend'], dict(before=11, after=10, cost=1))
        self.assertNotIn('选择', self.clicks())
        self.assertNotIn('挑战', self.clicks())

    def test_already_cleared_first_clear_claims_missions_with_zero_passes(self):
        self.frames([home(0), home(0), self.guild(), difficulty(), self.guild(),
                     catalogue(0, selected=False), self.guild(), mission_home(), mission_home(),
                     missions(), missions(), mission_receipt(), missions(claim=False), mission_home(badge=False)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertEqual(report['missions']['batches'], 1)
        self.assertEqual(report['entries'], 0)
        self.assertEqual(self.clicks().count('全部收取'), 1)

    def test_resumed_clear_result_collects_missions_only_after_unlock_and_balance(self):
        self.frames([score_result(), home(10), self.guild(), difficulty(), self.guild(),
                     catalogue(10, selected=False), self.guild(), mission_home(10), mission_home(10),
                     missions(), missions(), mission_receipt(), missions(claim=False), mission_home(10, badge=False)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertEqual(report['missions']['batches'], 1)
        self.assertEqual(report['spent'], 0)
        self.assertLess(self.clicks().index('跳过'), self.clicks().index('全部收取'))

    def test_unlocked_difficulty_does_not_consume_another_entry(self):
        self.frames([home(11), home(11), self.guild(), difficulty(), self.guild(),
                     cleared_preview(11, 10), self.guild(), home(11)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertEqual(report['entries'], 0)
        self.assertEqual(report['spent'], 0)
        self.assertNotIn('pending_spend', report)
        self.assertEqual(self.clicks().count('出发'), 1)

    def test_failed_boss_requires_explicit_retry_option(self):
        value = screen(('战斗失败', 480, 64), ('第1战', 122, 140),
                       ('结束', 577, 507), ('重新挑战', 808, 507))
        self.frames([value])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.task.ui.click.assert_not_called()

    def test_resumed_result_requires_unlock_proof_and_never_spends_a_new_pass(self):
        self.frames([inventory_result(), home(10), self.guild(), difficulty(), self.guild(),
                     cleared_preview(10, 9), self.guild(), home(10)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertTrue(report['settlement_resumed'])
        self.assertEqual(report['spent'], 0)
        self.assertEqual(report['entries'], 0)
        self.assertEqual(self.clicks().count('出发'), 1)

    def test_partial_reward_result_is_not_treated_as_a_first_clear(self):
        self.frames([inventory_result(), home(10), self.guild(), difficulty(), self.guild(), self.locked(), self.guild()])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['entries'], 0)
        self.assertNotIn('already_cleared', report)

    def test_score_result_is_closed_and_clear_is_proven_by_game_unlock(self):
        self.frames([score_result(), home(10), self.guild(), difficulty(), self.guild(),
                     cleared_preview(10, 9), self.guild(), home(10)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['boss_defeated'])
        self.assertTrue(report['already_cleared'])
        self.assertEqual(report['entries'], 0)
        self.assertEqual(self.clicks()[0], '关闭')

    def test_fresh_boss_clear_restores_difficulty_one_and_proves_unlock_before_completion(self):
        self.task.report.update(boss_defeated=True, entries=1,
                                pending_spend=dict(before=11, after=10, cost=1))
        self.task.exploration_verified = True
        self.frames([score_result(), home(10), self.guild(), difficulty(2), difficulty(1),
                     self.guild(), catalogue(10, selected=False), self.guild(), home(10)])
        self.task.explore(inventory_result())
        self.assertEqual(self.task.report['status'], 'complete')
        self.assertTrue(self.task.report['already_cleared'])
        self.assertEqual(self.task.report['spent'], 1)
        self.assertNotIn('pending_spend', self.task.report)
        self.assertIn('变更', self.clicks())
        self.assertEqual(self.clicks().count('出发'), 1)  # Read-only unlock probe.

    def test_chest_overlay_is_settled_before_inspecting_the_map_behind_it(self):
        receipt = screen(('宝箱开封结果', 480, 42), ('已开封从迷宫带回的宝箱。', 480, 85),
                         ('确认', 480, 480), ('黎明界迷宫', 130, 30), ('区域', 340, 30),
                         ('撤退', 680, 490), ('返回', 850, 490))
        self.frames([receipt, home(10), self.guild(), difficulty(), self.guild(),
                     cleared_preview(10, 9), self.guild(), home(10)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertEqual(report['entries'], 0)
        self.assertEqual(self.clicks()[0], '确认')

    def test_unlock_overlay_closes_before_home_probe_without_new_departure(self):
        notice = home(10)
        notice.items.extend(screen(('难度解锁', 480, 146), ('难度2已解锁。', 480, 271),
                                   ('关闭', 480, 370)).items)
        self.frames([notice, home(10), self.guild(), difficulty(), self.guild(),
                     cleared_preview(10, 9), self.guild(), home(10)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['entries'], 0)
        self.assertEqual(self.clicks()[0], '关闭')

    def test_home_departure_resumes_saved_boss_formation_without_new_entry(self):
        formation = screen(('队伍编组', 480, 42), ('队伍1', 98, 89), ('队伍2', 216, 89),
                           ('队伍3', 334, 89), ('取消', 712, 453))
        cv.rectangle(formation.image, (69, 82), (128, 97), (40, 190, 245), -1)
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457))
        self.frames([formation, formation, formation, stage])
        result = self.task.start(home(10))
        self.assertIs(result, stage)
        self.assertTrue(self.task.report['resumed'])
        self.assertEqual(self.task.report['entries'], 0)
        self.assertNotIn('pending_spend', self.task.report)
        self.assertEqual(self.clicks(), ['出发', '队伍1', '取消'])

    def test_damage_report_can_close_without_retrying_or_ending_exploration(self):
        report_screen = screen(('伤害报告', 480, 42), ('造成的伤害', 317, 76),
                               ('受到的伤害', 536, 76), ('确认', 478, 479))
        failure = screen(('战斗失败', 480, 64), ('第1战', 122, 140),
                         ('结束', 577, 507), ('重新挑战', 808, 507))
        self.frames([report_screen, failure])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(self.clicks(), ['确认'])
        self.assertEqual(report['entries'], 0)

    def test_retry_opens_one_formation_and_unknown_cost_is_not_confirmed(self):
        failure = screen(('战斗失败', 480, 64), ('第1战', 122, 140),
                         ('结束', 577, 507), ('重新挑战', 808, 507))
        self.task.options['retry_failed_boss'] = True
        self.task.exploration_verified = True
        self.frames([failure])
        with patch.object(self.task, 'wait', side_effect=EventUIError('合成的未知消费窗口')):
            report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertTrue(report['boss_retry'])
        self.assertEqual(self.clicks(), ['重新挑战'])
        self.assertEqual(report['entries'], 0)
        self.task.ui.click.reset_mock()
        with self.assertRaises(EventUIError):
            self.task.explore(failure)
        self.task.ui.click.assert_not_called()

    def test_clear_requires_boss_victory_and_matching_entry_balance(self):
        self.task.report.update(boss_defeated=True, pending_spend=dict(before=11, after=10, cost=1))
        with self.assertRaises(EventUIError):
            self.task.explore(home(11))
        self.assertIn('pending_spend', self.task.report)
        self.task.ui.click.assert_not_called()
        self.frames([self.guild(), difficulty(), self.guild(), catalogue(10, selected=False),
                     self.guild(), home(10)])
        self.task.explore(home(10))
        self.assertEqual(self.task.report['status'], 'complete')
        self.assertEqual(self.task.report['spent'], 1)
        self.assertNotIn('pending_spend', self.task.report)
        self.assertEqual(self.clicks().count('出发'), 1)
        self.assertNotIn('选择', self.clicks())

    def test_failed_battle_is_resolved_and_never_replayed(self):
        stage = screen(('战斗格子（普通）', 200, 55), ('挑战', 817, 455), blue=('挑战',))
        formation = screen(('队伍编组', 480, 42), ('战斗开始', 851, 453), blue=('战斗开始',))
        failure = screen(('战斗失败', 480, 64))
        self.frames([formation, failure])
        self.task.exploration_verified = True
        with patch.object(self.task, 'inspect_enemies', return_value=([dict(level=360)], stage)), \
                patch.object(self.task, 'get_formation', return_value=Mock(select_standard=Mock(return_value=([], formation)))), \
                patch('pcrscript.tasks.task_dawn_labyrinth_first_clear.EventCombat'):
            with self.assertRaises(EventUIError):
                self.task.fight(stage)
        self.assertEqual(self.task.report['battles'], 1)
        self.assertNotIn('pending_battle', self.task.report)
        self.assertEqual(self.task.report['history'][0]['outcome'], 'failed')
        self.assertEqual(self.clicks(), ['挑战', '战斗开始'])

    def test_missing_boss_strategy_preserves_saved_teams_and_never_starts_combat(self):
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457), blue=('挑战',))
        teams = [boss_formation(number) for number in (1, 2, 3)]
        ready, roles = boss_roster()
        explicit_names = [list(ready)[:5], list(ready)[5:10], list(ready)[10:15]]
        formation = Mock(spec=LabyrinthFormation)
        formation.audit_boss_roster.return_value = (ready, roles)
        formation.plan_boss_parties.side_effect = LabyrinthFormation.plan_boss_parties
        formation.clear_current.side_effect = teams
        formation.select_members.side_effect = [
            ([vars(ready[name]) for name in members], page)
            for members, page in zip(explicit_names, teams)]
        self.task.exploration_verified = True
        self.frames([teams[0], teams[0], teams[1], teams[2], teams[0], teams[1], teams[2]])
        with patch.object(self.task, 'inspect_enemies', return_value=([dict(level=350)], stage)), \
                patch.object(self.task, 'get_formation', return_value=formation), \
                patch('pcrscript.tasks.task_dawn_labyrinth_first_clear.EventCombat',
                      side_effect=EventUIError('未拦截未核验策略')):
            with self.assertRaises(EventUIError):
                self.task.fight(stage)
        formation.clear_current.assert_not_called()
        formation.select_members.assert_not_called()
        self.assertNotIn('战斗开始', self.clicks())
        self.assertNotIn('pending_battle', self.task.report)

    def test_current_boss_failure_obeys_retry_option_and_retries_only_once(self):
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457), blue=('挑战',))
        failure = screen(('战斗失败', 480, 64), ('第1战', 122, 140),
                         ('结束', 577, 507), ('重新挑战', 808, 507))
        teams = [boss_formation(number) for number in (1, 2, 3)]
        ready, roles = boss_roster()
        names = LabyrinthFormation.plan_boss_parties(ready, roles, strategy=synthetic_boss_strategy())
        for retry in (False, True):
            with self.subTest(retry=retry):
                self.task = DawnLabyrinthFirstClear(self.robot)
                self.task.ui = Mock(output=self.folder, last=None)
                self.task.ui.save.return_value = self.folder/'synthetic.png'
                self.task.options['retry_failed_boss'] = retry
                self.task.exploration_verified = True
                self.task.report.update(entries=1, pending_spend=dict(before=11, after=10, cost=1))
                formation = Mock(spec=LabyrinthFormation)
                formation.audit_boss_roster.return_value = (ready, roles)
                formation.plan_boss_parties.side_effect = lambda roster, roles: LabyrinthFormation.plan_boss_parties(roster, roles, strategy=synthetic_boss_strategy())
                formation.clear_current.side_effect = teams*2
                formation.select_members.side_effect = [
                    ([vars(ready[name]) for name in members], page)
                    for members, page in zip(names, teams)]*2
                fight_frames = [teams[0], teams[0], teams[1], teams[2],
                                teams[0], teams[1], teams[2], failure]
                self.frames([stage]+fight_frames+([teams[0], teams[0], stage]+fight_frames if retry else []))

                def click(button):
                    if getattr(button, 'text', '') == '重新挑战':
                        saved = json.loads((self.folder/'report.json').read_text(encoding='utf-8'))
                        self.assertTrue(saved['boss_retry'])
                        self.assertEqual(saved['battles'], 1)
                        self.assertNotIn('pending_battle', saved)
                        self.assertEqual(saved['history'][-1]['outcome'], 'failed')
                self.task.ui.click.side_effect = click
                with patch.object(self.task, 'inspect_enemies', return_value=([dict(level=350)], stage)), \
                        patch.object(self.task, 'get_formation', return_value=formation), \
                        patch('pcrscript.tasks.task_dawn_labyrinth_first_clear.EventCombat'):
                    report = self.task.run()
                fights = 2 if retry else 1
                self.assertEqual(report['status'], 'partial')
                self.assertEqual(report['battles'], fights)
                self.assertEqual([battle['outcome'] for battle in report['history']], ['failed']*fights)
                self.assertNotIn('pending_battle', report)
                self.assertNotIn('boss_defeated', report)
                self.assertEqual(self.clicks().count('战斗开始'), fights)
                self.assertEqual(self.clicks().count('重新挑战'), int(retry))
                self.assertEqual((report['entries'], report['spent']), (1, 0))
                self.assertEqual(report['pending_spend'], dict(before=11, after=10, cost=1))
                self.assertNotIn('出发', self.clicks())
                self.assertNotIn('结束', self.clicks())
                self.assertEqual(formation.audit_boss_roster.call_count, fights)
                self.assertEqual(formation.plan_boss_parties.call_count, fights)
                self.assertEqual(formation.clear_current.call_count, 3*fights)
                self.assertEqual(formation.select_members.call_count, 3*fights)
                self.assertEqual([call[0] for call in formation.method_calls[:3]],
                                 ['audit_boss_roster', 'plan_boss_parties', 'clear_current'])
                self.assertIn('已使用' if retry else '未启用', report['pending'][-1])

    def test_boss_preflight_failures_preserve_all_saved_teams(self):
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457), blue=('挑战',))
        teams = [boss_formation(number) for number in (1, 2, 3)]
        for cause in ('assets', 'audit', 'equipment', 'strategy', 'too_few'):
            with self.subTest(cause=cause):
                self.task.ui.click.reset_mock()
                self.task.exploration_verified = True
                self.frames([teams[0], teams[0], teams[1], teams[2], teams[0]])
                ready, roles = boss_roster()
                formation = Mock(spec=LabyrinthFormation)
                formation.audit_boss_roster.return_value = (ready, roles)
                strategy = synthetic_boss_strategy()
                formation.plan_boss_parties.side_effect = lambda roster, roles: LabyrinthFormation.plan_boss_parties(roster, roles, strategy=strategy)
                formation.clear_current.side_effect = teams
                if cause == 'audit':
                    formation.audit_boss_roster.side_effect = EventUIError('合成伙伴盘点失败')
                elif cause == 'equipment':
                    ready['合成伙伴0'].equipment = None
                elif cause == 'strategy':
                    strategy = replace(strategy, verified=False)
                elif cause == 'too_few':
                    for name in list(ready)[9:]:
                        ready.pop(name)
                with patch.object(self.task, 'inspect_enemies', return_value=([dict(level=350)], stage)), \
                        patch.object(self.task, 'get_formation', return_value=formation,
                                     side_effect=EventUIError('合成头像准备失败') if cause == 'assets' else None), \
                        patch('pcrscript.tasks.task_dawn_labyrinth_first_clear.EventCombat') as combat:
                    with self.assertRaises((EventUIError, KeyError)):
                        self.task.fight(stage)
                self.assertEqual(self.clicks(), ['挑战'])
                formation.clear_current.assert_not_called()
                formation.select_members.assert_not_called()
                combat.assert_not_called()
                self.assertEqual(self.task.report['battles'], 0)
                self.assertNotIn('pending_battle', self.task.report)

    def test_shop_is_closed_once_and_exit_confirmed_without_purchase(self):
        self.task.exploration_verified = True
        shop = screen(('商店', 480, 42), ('可使用阿尔法金币购买道具。', 480, 78),
                      ('购买', 240, 260), ('用300更新', 330, 485), ('关闭', 818, 475))
        confirm = screen(('商店', 480, 42), ('可使用阿尔法金币购买道具。', 480, 78),
                         ('商店确认', 480, 147), ('将退出商店。', 480, 235),
                         ('确认', 590, 370), ('关闭', 818, 475), blue=('确认',))
        map_screen = screen(('黎明界迷宫', 130, 30), ('区域', 340, 30),
                            ('撤退', 680, 490), ('返回', 850, 490))
        self.frames([shop, confirm, map_screen])
        self.task.run()
        self.assertEqual(self.clicks(), ['关闭', '确认'])

    def test_confirm_persisted_before_single_entry_and_unknown_state_does_not_restart(self):
        self.frames([home(11), home(11), self.guild(), difficulty(), self.guild(), self.locked(), self.guild(), departure(), screen(('未知页面', 480, 200))])
        def click(button):
            if getattr(button, 'center', (0, 0))[1] == 475:
                saved = json.loads((self.folder/'report.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['pending_spend']['cost'], 1)
        self.task.ui.click.side_effect = click
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['entries'], 1)
        self.assertEqual(report['pending_spend']['after'], 10)
        self.assertEqual(self.clicks().count('出发'), 2)  # Open guilds, then one committed entry.
        self.assertNotIn('战斗开始', self.clicks())

    def test_balance_mismatch_is_never_committed(self):
        self.frames([home(11), home(11), self.guild(), difficulty(), self.guild(), self.locked(), self.guild(), departure(10, 9)])
        report = self.task.run()
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['entries'], 0)
        self.assertNotIn('pending_spend', report)

    def test_cancellation_at_departure_keeps_pending_confirmation(self):
        self.frames([home(11), home(11), self.guild(), difficulty(), self.guild(), self.locked(), self.guild(), departure()])
        def click(button):
            if getattr(button, 'center', (0, 0))[1] == 475:
                raise RunCancelled('synthetic cancellation')
        self.task.ui.click.side_effect = click
        with self.assertRaises(RunCancelled):
            self.task.run()
        saved = json.loads((self.folder/'report.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['status'], 'cancelled')
        self.assertEqual(saved['pending_spend']['cost'], 1)

    def test_resumed_unknown_enemy_level_does_not_depart_or_fight(self):
        value = screen(('战斗格子（普通）', 200, 55), ('挑战', 817, 455), blue=('挑战',))
        self.frames([value])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertTrue(report['resumed'])
        self.assertEqual(report['entries'], 0)
        self.task.ui.click.assert_not_called()

    def test_resuming_other_difficulty_never_fights_or_selects_rewards(self):
        value = screen(('获得道具的机会！', 480, 50), ('请选择要获得的迷宫遗物。', 480, 92),
                       ('难度详情', 742, 220), ('设定', 818, 220), ('玩法', 742, 330),
                       ('2', 743, 200), ('菜单', 915, 40))
        self.frames([value])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertIn('不是已核验的难度1', report['pending'][0])
        self.assertFalse(self.task.exploration_verified)
        self.task.ui.click.assert_not_called()

    def test_resumed_difficulty_icon_tracks_menu_position(self):
        for x, y in ((742, 220), (722, 238), (742, 109)):
            value = screen(('战斗格子（普通）', 138, 56), ('挑战', 817, 457),
                           ('难度详情', x, y), ('设定', x+76, y),
                           ('玩法', x, y+110), ('1', x, y-20), ('菜单', 894, 72))
            stage = screen(('战斗格子（普通）', 138, 56), ('挑战', 817, 457))
            self.frames([stage])
            with self.assertRaisesRegex(EventUIError, '同行公会无法核验'):
                self.task.verify_exploration(value)
            self.assertFalse(self.task.exploration_verified)
            self.task.ui.click.assert_not_called()
            self.task.ui.number.assert_called_with(value, (x-8, y-30, x+11, y-4))

    def test_resumed_initial_selection_never_prepares_or_changes_partners(self):
        for count in ('0/3', '2/3'):
            with self.subTest(count=count):
                value = screen(('角色选择', 480, 42), (count, 910, 80), ('去邀请', 817, 475),
                               ('难度2', 700, 120), ('其他公会', 700, 150), blue=('去邀请',))
                self.frames([value])
                with patch.object(self.task, 'get_formation') as formation:
                    report = self.task.run()
                self.assertEqual(report['status'], 'partial')
                self.assertIn('难度与同行公会无法核验', report['pending'][-1])
                self.assertFalse(self.task.exploration_verified)
                formation.assert_not_called()
                self.task.ui.click.assert_not_called()
                self.assertEqual((report['entries'], report['battles']), (0, 0))

    def test_resumed_departure_reward_is_not_closed_before_context_validation(self):
        self.frames([screen(('出发奖励', 480, 42), ('关闭', 480, 475))])
        self.assertEqual(self.task.run()['status'], 'partial')
        self.task.ui.click.assert_not_called()

    def test_settlement_resume_flag_cannot_authorize_initial_partner_selection(self):
        self.task.report['settlement_resumed'] = True
        value = screen(('角色选择', 480, 42), ('0/3', 910, 80), ('去邀请', 817, 475))
        with patch.object(self.task, 'get_formation') as formation:
            with self.assertRaisesRegex(EventUIError, '同行公会'):
                self.task.explore(value)
        formation.assert_not_called()
        self.task.ui.click.assert_not_called()

    def test_difficulty_one_and_other_guild_never_authorize_a_saved_run(self):
        value = screen(('战斗格子（普通）', 138, 56), ('挑战', 817, 457),
                       ('难度详情', 742, 220), ('设定', 818, 220), ('玩法', 742, 330),
                       ('1', 743, 200), ('菜单', 915, 40), ('同行公会', 300, 150),
                       ('其他公会', 430, 150), ('确认', 590, 370), ('选择', 202, 464))
        self.frames([value])
        with patch.object(self.task, 'get_formation') as formation, patch.object(self.task, 'fight') as fight:
            self.assertEqual(self.task.run()['status'], 'partial')
        self.assertIn('同行公会无法核验', self.task.report['pending'][-1])
        self.assertIn('difficulty_evidence', self.task.report)
        self.assertFalse(self.task.exploration_verified)
        self.task.ui.click.assert_not_called()
        formation.assert_not_called()
        fight.assert_not_called()

    def test_unverified_shop_or_boss_failure_is_not_changed(self):
        self.task.options['retry_failed_boss'] = True
        for value in (screen(('商店', 480, 42), ('可使用阿尔法金币购买道具。', 480, 78),
                             ('关闭', 818, 475)),
                      screen(('战斗失败', 480, 64), ('第1战', 122, 140),
                             ('结束', 577, 507), ('重新挑战', 808, 507))):
            with self.subTest(page=value.text()):
                self.frames([value])
                self.assertEqual(self.task.run()['status'], 'partial')
                self.task.ui.click.assert_not_called()
                self.assertNotIn('boss_retry', self.task.report)

    def test_verified_fresh_departure_authorizes_initial_selection(self):
        value = screen(('角色选择', 480, 42), ('0/3', 910, 80), ('去邀请', 817, 475))
        self.frames([self.guild(), difficulty(), self.guild(), self.locked(), self.guild(), departure(), value])
        self.assertIs(self.task.start(home(11)), value)
        self.assertTrue(self.task.exploration_verified)
        self.assertEqual(self.task.report['exploration_context']['guild'], '美食殿堂')
        self.assertEqual(self.task.report['exploration_context']['difficulty'], 1)
        formation = Mock(choose_initial=Mock(return_value=[vars(ready_character('合成伙伴'))]))
        with patch.object(self.task, 'get_formation', return_value=formation), \
                patch.object(self.task, 'capture', side_effect=EventUIError('合成后续停止')):
            with self.assertRaisesRegex(EventUIError, '合成后续停止'):
                self.task.explore(value)
        formation.choose_initial.assert_called_once_with(value)

    def test_saved_departure_report_is_not_reused_as_current_guild_proof(self):
        self.task.report['exploration_context'] = dict(difficulty=1, guild='美食殿堂')
        value = screen(('角色选择', 480, 42), ('0/3', 910, 80))
        with self.assertRaisesRegex(EventUIError, '同行公会'):
            self.task.explore(value)
        self.assertFalse(self.task.exploration_verified)
        self.task.ui.click.assert_not_called()

    def test_difficulty_one_scrolls_back_when_unlock_selected_difficulty_two(self):
        hidden = screen(('难度变更', 480, 42), ('难度2', 330, 90),
                        ('取消', 370, 480), ('变更', 588, 480))
        self.frames([hidden, difficulty(2), difficulty(1), self.guild()])
        self.assertTrue(maze.guild_selection(self.task.difficulty_one(self.guild())))
        self.task.ui.swipe.assert_called_once_with((615, 165), (615, 395))
        self.assertEqual(self.clicks()[-1], '变更')

    def test_bad_options_fail_before_device_connection(self):
        for options in (None, [], {'timeout': True}, {'timeout': 7201}, {'max_battles': 0}, {'max_battles': 61}, {'retry_failed_boss': 1}):
            with self.subTest(options=options), patch('pcrscript.runtime.robot_from_config') as connect:
                with self.assertRaises(ValueError):
                    run_task_with_config({'DawnLabyrinthFirstClear': options}, 'dawn_labyrinth_first_clear')
                connect.assert_not_called()
