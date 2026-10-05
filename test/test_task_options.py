"""Configuration boundaries shared by the real task preparation entry points."""
from copy import deepcopy
from functools import partial
from unittest import TestCase
from unittest.mock import patch

from pcrscript.tasks import (AbyssPush, AbyssSubjugation, DawnLabyrinth,
                            DawnLabyrinthFirstClear, Recollection, RecollectionFirstClear, TeamBattle)
from pcrscript.tasks import (task_abyss, task_abyss_subjugation, task_dawn_labyrinth,
                            task_dawn_labyrinth_first_clear, recollection_flow, task_team_battle)


CASES = (
    (AbyssPush, task_abyss.validate_options, 'max_failures_per_stage', 50, 'allow_local_trials'),
    (AbyssSubjugation, task_abyss_subjugation.validate_options, 'max_boss_tickets', 999, 'first_clear'),
    (DawnLabyrinth, task_dawn_labyrinth.validate_options, 'max_passes', 99, None),
    (DawnLabyrinthFirstClear, task_dawn_labyrinth_first_clear.validate_options, 'max_battles', 60, 'retry_failed_boss'),
    (Recollection, recollection_flow.validate_options, 'max_sweeps', 99, 'preview_only'),
    (RecollectionFirstClear, partial(recollection_flow.validate_options, first_clear=True),
     'max_attempts_per_stage', 5, 'auto_equip'),
    (TeamBattle, task_team_battle.validate_options, 'max_real_attacks', 3, 'simulation_only'),
)


class TaskOptionsTests(TestCase):
    def test_invalid_config_fails_in_prepare_before_external_work(self):
        with patch('pcrscript.news.fetch_event_news') as fetch:
            for task, _, budget, upper, flag in CASES:
                invalid = [None, [], [('timeout', 1)]]
                invalid += [{budget: value} for value in (True, False, 0, -1, upper+1, 1.0, '1', None)]
                if flag:
                    invalid += [{flag: value} for value in (0, 1, 'true', None)]
                for options in invalid:
                    with self.subTest(task=task.name, options=options):
                        with self.assertRaisesRegex(ValueError, task.config_section):
                            task.prepare({task.config_section: options})
            fetch.assert_not_called()

    def test_defaults_and_overrides_do_not_mutate_saved_configuration(self):
        for task, validate, budget, upper, flag in CASES:
            for amount in (1, upper):
                with self.subTest(task=task.name, amount=amount):
                    raw = {budget: amount, 'output': 'synthetic/output', 'sources': {'limit': 2}}
                    if flag:
                        raw[flag] = False
                    original = deepcopy(raw)
                    result = validate(raw)
                    self.assertEqual(raw, original)
                    self.assertIsNot(result, raw)
                    self.assertEqual(result[budget], amount)
                    self.assertGreater(result['timeout'], 0)
                    self.assertEqual(result['sources'], raw['sources'])
                    self.assertEqual(result['output'], raw['output'])
                    if flag:
                        self.assertIs(result[flag], False)
