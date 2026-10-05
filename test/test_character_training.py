"""Synthetic owned training audits; no account data or device operations."""
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2 as cv

from pcrscript.game_ui.character_training import (SKILL_GROUPS, owned_six_stars,
    training_skill_levels, inspect_owned_training)
from pcrscript.game_ui.ordinary_equipment import inspect_ordinary_equipment
from pcrscript.run_session import RunCancelled
from test_dawn_labyrinth import screen
from test_ordinary_equipment import slot


DEFINITIONS = dict(union_burst='合成爆发', union_burst_evolution='合成爆发+',
                   main_skill_1='合成技能甲', main_skill_evolution_1='合成技能甲+',
                   main_skill_2='合成技能乙', ex_skill_1='合成EX')


def memory():
    value = screen(('角色强化', 125, 30), ('技能强化', 656, 75),
                   ('合成角色的纯净记忆碎片', 680, 128))
    for i, x in enumerate((152, 190, 228, 266, 304, 342)):
        cv.rectangle(value.image, (x-10,318), (x+10,349),
                     (180,70,220) if i == 5 else (20,190,240), -1)
    return value


def skills(values=(365,365,365,365)):
    value = memory()
    value.items = screen(('角色强化', 125, 30), ('技能强化', 656, 75)).items
    for i, (keys, level) in enumerate(zip(SKILL_GROUPS, values)):
        value.items += screen((DEFINITIONS[keys[0]], 650, 140+80*i),
                              ('Lv.'+str(level), 850, 140+80*i)).items
    return value


class CharacterTrainingTests(TestCase):
    def test_only_active_six_star_layout_proves_six_stars(self):
        self.assertEqual(owned_six_stars(memory()), 6)
        for index, color in ((0,(245,245,245)), (5,(245,245,245)),
                             (5,(240,170,20)), (5,(20,190,240))):
            value = memory()
            x = (152,190,228,266,304,342)[index]
            cv.rectangle(value.image,(x-10,318),(x+10,349),color,-1)
            self.assertIsNone(owned_six_stars(value))
        five = screen()
        for x in (171,212,253,294,335):
            cv.rectangle(five.image,(x-10,318),(x+10,349),(20,190,240),-1)
        self.assertIsNone(owned_six_stars(five))

    def test_all_four_levels_include_ub_and_ex_and_accept_current_evolved_titles(self):
        for index in range(4):
            values = [365]*4
            values[index] = 364
            result = training_skill_levels(skills(values), DEFINITIONS)
            self.assertEqual(min(result.values()), 364)
        value = skills()
        value.items[2].text = '合成爆发+'
        value.items[4].text = '合成技能甲+'
        self.assertEqual(set(training_skill_levels(value,DEFINITIONS)), {keys[0] for keys in SKILL_GROUPS})

    def test_incomplete_weak_ambiguous_or_preview_levels_stay_unknown(self):
        for index in range(4):
            for kind in ('missing', 'weak_title', 'weak_level', 'unknown_title', 'cap', 'preview', 'duplicate'):
                with self.subTest(index=index, kind=kind):
                    value = skills()
                    title, level = value.items[2+index*2:4+index*2]
                    if kind == 'missing':
                        value.items.remove(level)
                    elif kind == 'weak_title':
                        title.score = .94
                    elif kind == 'weak_level':
                        level.score = .94
                    elif kind == 'unknown_title':
                        title.text = '另一个衣装的技能'
                    elif kind == 'cap':
                        level.text = '上限Lv.365'
                    elif kind == 'preview':
                        level.text = 'Lv.365→Lv.366'
                    else:
                        value.items += screen(('Lv.364',860,level.center[1])).items
                    self.assertIsNone(training_skill_levels(value, DEFINITIONS))
        self.assertIsNone(training_skill_levels(skills(), {k:v for k,v in DEFINITIONS.items() if k != 'ex_skill_1'}))

    def test_reader_saves_live_evidence_without_any_training_submission(self):
        ui = Mock(save=Mock(return_value='synthetic.png'), wait=Mock(return_value=skills((365,366,365,367))))
        with patch('pcrscript.game_ui.character_training.character',return_value={'training_skills':DEFINITIONS}):
            result = inspect_owned_training(ui,'合成角色',memory())
        self.assertEqual((result['stars'],result['skill_level']), (6,365))
        self.assertEqual(len(result['training_evidence']),2)
        ui.expect_click.assert_called_once_with('技能强化',(615,55,700,95),exact=True)
        ui.click.assert_not_called()
        self.assertTrue(ui.wait.call_args.args[0](skills()))
        self.assertFalse(ui.wait.call_args.args[0](slot(0)))

    def test_unknown_stars_or_catalogue_do_not_open_training_controls(self):
        for value, definitions in ((screen(),DEFINITIONS),(memory(),{})):
            ui = Mock(save=Mock(return_value='synthetic.png'))
            with patch('pcrscript.game_ui.character_training.character',return_value={'training_skills':definitions}):
                result = inspect_owned_training(ui,'合成角色',value)
            self.assertIsNone(result['skill_level'])
            ui.expect_click.assert_not_called()

    def test_cancellation_during_read_leaves_no_cleanup_or_training_input(self):
        ui = Mock(save=Mock(return_value='synthetic.png'),wait=Mock(return_value=skills()))
        check = Mock(side_effect=[None,RunCancelled('synthetic stop')])
        with patch('pcrscript.game_ui.character_training.character',return_value={'training_skills':DEFINITIONS}), \
                self.assertRaises(RunCancelled):
            inspect_owned_training(ui,'合成角色',memory(),check=check)
        ui.expect_click.assert_called_once_with('技能强化',(615,55,700,95),exact=True)
        ui.click.assert_not_called()

    def test_ordinary_audit_integrates_actual_owned_training_only_when_requested(self):
        frames = [slot(i,'future' if i<2 else 'equipped') for i in range(6)]
        ui = Mock(save=Mock(return_value='synthetic.png'))
        ui.number.side_effect = lambda s,roi: s.number(roi)
        ui.wait.side_effect = [frames[0]]+frames+[skills((365,365,364,365))]
        with patch('pcrscript.game_ui.ordinary_equipment.open_character_memory',return_value=memory()), \
                patch('pcrscript.game_ui.character_training.character',return_value={'training_skills':DEFINITIONS}):
            result = inspect_ordinary_equipment(ui,'合成角色',inspect_training=True)
        self.assertEqual((result['stars'],result['skill_level']), (6,364))
        self.assertEqual(result['values'],dict(equipment=4,equipment_available=4))
        self.assertEqual(len(result['training_evidence']),2)
        self.assertEqual([call.args[0] for call in ui.click.call_args_list],
                         [(130,141),(96,229),(129,317),(365,141),(402,229),(365,317)])
