"""Synthetic regression coverage for shared selection and cultivation boundaries."""
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import numpy as np
import cv2 as cv

from pcrscript.game_ui.guide_vision import labeled_fields
from pcrscript.game_ui.character_equipment import unique_equipment_fields, second_unique_selector
from pcrscript.game_ui.character_search import search_character
from pcrscript.game_ui.screen import EventUIError
from pcrscript.game_ui.special_equipment import loadout_items, same_loadout
from pcrscript.tasks.event_strategy import CharacterStatus, EventParty, MemberRequirement, readiness
from pcrscript.tasks.party_preparation import (audit_declared_build, cultivation_plan, rank_candidates,
    source_candidates, prepare_special, upgrade_party_stars, party_fingerprint)
from pcrscript.tasks.strategy_document import Evidence, empty_member, finalize, to_event_party
from pcrscript.tasks.strategy_formation import StrategyFormation
from pcrscript.tasks.abyss_party import AbyssFormation
from pcrscript.tasks.subjugation_party import SubjugationFormation
from functools import partial
from ui_fixtures import screen as synthetic_screen


def party(name='guide', names='abcde'):
    return EventParty(name, 'https://example.com/'+name,
        [MemberRequirement(n, 100, 10, 5, True, False, i % 2 == 0, 100)
         for i, n in enumerate(names)], build_basis='local_trial', auto=False)


def statuses(team):
    return [CharacterStatus(m.name, m.level, m.rank, m.stars, m.unique, m.unique2,
                            m.skill_level, identity_verified=True,
                            unique_level=m.unique_level, unique2_stars=m.unique2_stars) for m in team.members]


screen = partial(synthetic_screen, background=100, box_half_size=(20, 8))


class PartyPreparationTests(TestCase):
    def test_character_list_search_recovers_dropped_input_and_confirms_android_edit(self):
        ui = Mock()
        state = dict(inputs=0, committed=False, resets=0)
        def capture(**kwargs):
            labels = [('角色一览', 120, 30), ('重置', 689, 90)]
            if state['committed']:
                labels.append(('合成角色', 480, 90))
            elif state['inputs'] >= 2:
                labels.extend([('合成角色', 100, 490), ('确定', 875, 490)])
            return screen(*labels)
        def click(pos, **kwargs):
            if pos == (689, 90):
                state['resets'] += 1
            elif getattr(pos, 'text', None) == '确定':
                state['committed'] = True
            elif pos == (480, 115):
                self.assertTrue(state['committed'])
        ui.capture.side_effect = capture
        ui.click.side_effect = click
        ui.driver.input.side_effect = lambda text: state.update(inputs=state['inputs']+1)
        with patch('pcrscript.game_ui.character_search.time.sleep'), \
                patch('pcrscript.game_ui.character_search.time.monotonic', side_effect=range(0, 100, 4)):
            result = search_character(ui, '合成角色(夏日)', page='角色一览', page_area=(40,0,250,65),
                field_area=(330,65,640,110), reset=(689,90), field=(480,90), defocus=(480,115))
        self.assertEqual(state['inputs'], 2)
        self.assertEqual(state['resets'], 2)
        self.assertIsNotNone(result.find('合成角色'))

    def test_both_tasks_use_the_same_account_selector(self):
        self.assertIs(AbyssFormation, StrategyFormation)
        self.assertTrue(issubclass(SubjugationFormation, StrategyFormation))

    def test_installed_zero_stage_weapon_is_not_absent_or_character_rarity(self):
        self.assertEqual(labeled_fields('5星 专武2:0星'), dict(stars=5, unique2=True, unique2_stars=0))
        self.assertEqual(labeled_fields('等级100 专武1等级310'), dict(level=100, unique=True, unique_level=310))
        self.assertEqual(labeled_fields('专武1:310 专武2未装备'), dict(unique=True, unique_level=310, unique2=False))
        self.assertEqual(labeled_fields('专130'), dict(unique=True, unique_level=130))
        self.assertEqual(labeled_fields('专武2:0'), {})  # No explicit installation or stage label.

    def test_numeric_equipment_requirements_survive_source_export(self):
        members = [empty_member(n) for n in 'abcde']
        for m in members:
            for k, v in dict(level=100, rank=10, stars=5, unique=True, unique2=True,
                             skill_level=100, instant=True, unique_level=310, unique2_stars=0).items():
                m[k].add(v, Evidence('https://example.com/synthetic', method='named_field'))
        raw = finalize(dict(source='https://example.com/synthetic', scope={}, scope_verified=True,
            region='cn', target_region='cn', members=members,
            auto=dict(value=True, evidence=[{}], conflicts=[])))
        team = to_event_party(raw)
        self.assertEqual(team.members[0].unique_level, 310)
        self.assertEqual(team.members[0].unique2_stars, 0)
        actual = statuses(team)[0]
        self.assertEqual(readiness(team.members[0], actual), [])
        self.assertTrue(readiness(team.members[0], replace(actual, unique2=False)))
        self.assertTrue(readiness(team.members[0], replace(actual, unique_level=30)))
        self.assertTrue(readiness(team.members[0], replace(actual, unique2_stars=None)))

    def test_slot_reader_does_not_confuse_character_level_or_infer_second_slot(self):
        observed = screen(('角色强化', 110, 35), ('等级365', 200, 425),
                          ('等级310', 700, 233), ('此专用装备1已强化至强化等级上限。', 700, 389))
        values = unique_equipment_fields(observed)
        self.assertEqual(values, dict(unique=True, unique_available=True, unique_level=310))
        self.assertNotIn('unique2', values)
        self.assertEqual(unique_equipment_fields(screen(('此专用装备2预定今后登场。', 700, 335))),
                         dict(unique2=False, unique2_available=False))
        self.assertEqual(unique_equipment_fields(screen(('专用装备2', 700, 130))), {})

    def test_second_weapon_requires_its_own_icon_and_max_stage_evidence(self):
        observed = screen(('角色强化',110,35), ('等级270',172,142),
                          ('此专用装备1已强化至强化等级上限。',700,389))
        cv.rectangle(observed.image, (288,78), (361,150), (255,255,255), 2)
        self.assertIsNotNone(second_unique_selector(observed))
        single = screen(('角色强化',110,35), ('等级270',248,142))
        cv.rectangle(single.image, (212,78), (285,150), (255,255,255), 2)
        self.assertIsNone(second_unique_selector(single))
        maximum = screen(('此专用装备2已强化至最强。',700,389))
        self.assertNotIn('unique2_stars', unique_equipment_fields(maximum))
        for x in (662,673,684,695,706):
            maximum.image[228:238,x-4:x+4] = (0,200,255)
        self.assertEqual(unique_equipment_fields(maximum)['unique2_stars'],5)
        maximum.items = []
        self.assertEqual(unique_equipment_fields(maximum),{})

    def test_installation_and_enhancement_have_separate_gaps_and_dependencies(self):
        team = party()
        team.members[0] = replace(team.members[0], unique2=True, unique_level=310, unique2_stars=5)
        actual = statuses(team)
        actual[0] = replace(actual[0], unique=False, unique2=False, unique_level=None, unique2_stars=None)
        rows = cultivation_plan(team, actual)['gaps']
        self.assertEqual([r['field'] for r in rows if r['action'] == 'install'], ['unique', 'unique2'])
        self.assertEqual(next(r for r in rows if r['field'] == 'unique2')['prerequisite'], 'unique')
        self.assertTrue(all(not r['executable'] for r in rows))
        self.assertIn('unique2_stars', [r['field'] for r in rows if r['action'] == 'inspect'])

    def test_original_sources_are_exhausted_before_any_substitution(self):
        a, b = party('needs-work'), party('owned', 'abcdf')
        actual = {v.name: v for v in statuses(b)}
        a.members[0].rank = 9  # Exact lower Rank cannot be repaired by levelling.
        fetch = Mock(side_effect=[[a, b], [party('later', 'abcdg')], []])
        candidates = list(source_candidates(fetch, lambda: actual))
        self.assertEqual([(c.party.name, c.allow_substitutions) for c in candidates[:3]],
                         [('owned', False), ('needs-work', False), ('later', False)])
        self.assertTrue(all(c.allow_substitutions for c in candidates[3:]))
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(rank_candidates([a, b], actual)[0].name, 'owned')

    def test_repeated_catalog_is_deduplicated_within_the_batch_limit(self):
        first, second = party(), party()
        second.members[0].instant = False
        self.assertNotEqual(party_fingerprint(first), party_fingerprint(second))
        fetch = Mock(return_value=[first, second])
        result = list(source_candidates(fetch, lambda: {}, max_batches=10))
        self.assertEqual(len(result), 4)
        self.assertEqual(fetch.call_count, 10)

    def test_duplicate_batch_does_not_hide_a_later_distinct_source(self):
        first, later = party('first'), party('later', 'abcdf')
        duplicate = replace(first, name='same-party-new-guide', source='https://example.com/another-guide')
        fetch = Mock(side_effect=[[first], [duplicate], [later]])
        available = Mock(return_value=[])
        result = list(source_candidates(fetch, lambda: {}, max_batches=3,
                                        available=available, allow_substitutions=False))
        self.assertEqual([c.party.name for c in result], ['first', 'later'])
        self.assertEqual([c.kwargs['advance'] for c in fetch.call_args_list], [False, True, True])
        self.assertEqual(available.call_count, 2)

    def test_complete_guides_have_explicit_substitution_policy_and_distinct_damage_goals(self):
        first, second = party(), party()
        first.build_basis = second.build_basis = 'source'
        second.damage_reference = dict(damage=40000000, scope=dict(kind='boss', boss='合成首领'),
                                      evidence=[dict(source='https://example.com/synthetic')])
        fetch = Mock(return_value=[first, second])
        self.assertNotEqual(party_fingerprint(first), party_fingerprint(second))
        strict = list(source_candidates(fetch, lambda: {}, allow_substitutions=False))
        self.assertEqual(len(strict), 2)
        self.assertTrue(all(not c.allow_substitutions for c in strict))
        adapted = list(source_candidates(fetch, lambda: {}, allow_substitutions=True))
        self.assertEqual([c.allow_substitutions for c in adapted], [False, False, True, True])

    def test_empty_parsed_batch_does_not_hide_a_later_source(self):
        candidate = party('later')
        fetch = Mock(side_effect=[[], [candidate], []])
        result = list(source_candidates(fetch, lambda: {}, max_batches=3))
        self.assertEqual([(c.party.name, c.allow_substitutions) for c in result],
                         [('later', False), ('later', True)])
        self.assertEqual(fetch.call_count, 3)

    def test_partial_source_keeps_rank_star_and_second_weapon_requirements(self):
        declared = party()
        declared.members[0] = replace(declared.members[0], rank=None, stars=3, unique2=True, unique2_stars=0)
        current = party()
        audit = dict(order=list('abcde'), observed=[asdict(a) for a in statuses(current)])
        self.assertFalse(audit_declared_build(Mock(), current, audit, declared.members))
        failures = str(audit['unready'])
        self.assertIn('星级', failures)
        self.assertIn('专武2', failures)
        self.assertNotIn('装备Rank', failures)

    def test_special_equipment_checks_item_identity_and_live_members_before_paid_combat(self):
        team = party()
        frame = np.full((540, 960, 3), 100, np.uint8)
        proof = dict(order=list('abcde'), slots=[[True]*3 for _ in range(5)],
                     empty=0, unknown=0, items=loadout_items(frame))
        other = dict(proof, items=loadout_items(np.full_like(frame, 200)))
        self.assertTrue(same_loadout(proof, proof))
        self.assertFalse(same_loadout(proof, other))
        formation = Mock(inspect_current=Mock(return_value=statuses(team)))
        with patch('pcrscript.tasks.party_preparation.auto_equip_special', return_value=proof) as equip, \
             patch('pcrscript.tasks.party_preparation.inspect_special_equipment', return_value=other):
            self.assertEqual(prepare_special(formation, team, list('abcde')), proof)
            with self.assertRaisesRegex(EventUIError, '必须重新模拟'):
                prepare_special(formation, team, list('abcde'), expected=proof)
            self.assertEqual(equip.call_count, 1)
            formation.inspect_current.return_value = statuses(party(names='abcdf'))
            with self.assertRaisesRegex(EventUIError, '编队发生变化'):
                prepare_special(formation, team, list('abcde'))

    def test_shared_star_training_preserves_source_three_stars_and_auto(self):
        team = party()
        actual = statuses(team)
        actual[0].stars = actual[1].stars = 3
        team.members[0].stars = team.members[1].stars = 3
        declared = [replace(m, stars=None) for m in team.members]
        declared[0].stars = 3
        before = dict(order=list('abcde'), observed=[asdict(a) for a in actual])
        after = [replace(a, stars=5) if a.name == 'b' else a for a in actual]
        updated = replace(team, members=[replace(m, stars=5) if m.name == 'b' else m for m in team.members])
        formation = Mock(observed={a.name: a for a in actual},
            select=Mock(return_value=(True, {})),
            current_trial=Mock(return_value=(updated, dict(order=list('abcde'), observed=[asdict(a) for a in after]))))
        with patch('pcrscript.game_ui.character_stars.upgrade_to_five') as upgrade:
            result, audit = upgrade_party_stars(formation, team, before,
                options=dict(allow_five_star_upgrade=True), report={}, save=Mock(),
                leave=Mock(), reopen=Mock(), stage=SimpleNamespace(), declared=declared)
            self.assertEqual([c.args[1] for c in upgrade.call_args_list], ['b'])
            self.assertIs(result.auto, False)
            self.assertEqual([m.instant for m in result.members], [m.instant for m in team.members])
            self.assertEqual(result.members[0].stars, 3)

    def test_other_members_star_conflicts_block_all_star_spending(self):
        for required, current in ((3, 4), (3, 2), (3, None), (6, 5), (5, 6)):
            with self.subTest(required=required, current=current):
                team = party()
                team.members[1].stars = required
                actual = statuses(team)
                actual[0].stars = 3  # This member can be upgraded to the required five stars.
                actual[1].stars = current
                before = dict(order=list('abcde'), observed=[asdict(a) for a in actual])
                formation, leave, reopen, save = Mock(), Mock(), Mock(), Mock()
                report = {}
                with patch('pcrscript.game_ui.character_stars.upgrade_to_five',
                           side_effect=AssertionError('Incompatible party must not spend on stars')) as upgrade:
                    result, audit = upgrade_party_stars(formation, team, before,
                        options=dict(allow_five_star_upgrade=True, allow_divine_amulets=True),
                        report=report, save=save, leave=leave, reopen=reopen,
                        stage=SimpleNamespace(), declared=team.members)
                    self.assertIsNone(result)
                    self.assertEqual(audit['unready'][0]['character'], 'b')
                    self.assertIn('星级', str(audit['unready']))
                    self.assertEqual(team.members[1].stars, required)
                    self.assertEqual(report, {})
                    upgrade.assert_not_called()
                    leave.assert_not_called()
                    reopen.assert_not_called()
                    save.assert_not_called()
                    formation.select.assert_not_called()

    def test_other_build_gaps_block_star_spending_and_preview_is_read_only(self):
        team = party()
        actual = statuses(team)
        actual[0].stars, actual[0].rank = 3, 11
        before = dict(order=list('abcde'), observed=[asdict(a) for a in actual])
        formation, leave = Mock(), Mock()
        with patch('pcrscript.game_ui.character_stars.upgrade_to_five') as upgrade:
            args = dict(options=dict(allow_five_star_upgrade=True), report={}, save=Mock(),
                        leave=leave, reopen=Mock(), stage=SimpleNamespace(), declared=team.members)
            result, audit = upgrade_party_stars(formation, team, before, **args)
            self.assertIsNone(result)
            self.assertIn('装备Rank', str(audit['unready']))
            args['options']['preview_only'] = True
            self.assertIs(upgrade_party_stars(formation, team, before, **args)[0], team)
            upgrade.assert_not_called()
            leave.assert_not_called()
