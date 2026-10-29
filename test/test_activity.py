"""Synthetic activity scheduling; game handlers keep their own UI regressions."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from pcrscript.tasks import Event, EventNews, find_taskclass
from pcrscript.tasks.task_activity import ActivityDaily, activity_options
from pcrscript.tasks.task_story_event import CampaignClean
from pcrscript.tasks.task_collaboration_raid import CollaborationRaid
from pcrscript.tasks.task_revival_event import RevivalEventOnce
from pcrscript.runtime import modify_task_list, run_task_from_config


class ActivityTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def robot(self, config):
        return SimpleNamespace(driver=Mock(), task_config=config, _task_output=self.root)

    def test_concurrent_types_keep_config_reports_and_options_separate(self):
        config = dict(Activities=dict(types=['collaboration_raid', 'revival', 'story'],
                      options=dict(collaboration_raid=dict(max_tickets=3))),
                      CollaborationRaid=dict(max_tickets=9), StoryEvent=dict(exchange=False),
                      RevivalEvent=dict(account_key='synthetic'))
        original = copy.deepcopy(config)
        seen = []
        def run(child, *args, **kwargs):
            seen.append((child.config_section, child.task_options(), args, kwargs))
            return dict(status='complete')
        event = Event(0, 10**12, 'Synthetic revival', dict(event_id=1))
        with patch.object(CollaborationRaid, 'run', run), patch.object(CampaignClean, 'run', run), \
             patch.object(RevivalEventOnce, 'run', run), \
             patch('pcrscript.news.fetch_event_news', return_value=EventNews(revival=event)), \
             patch('pcrscript.tasks.task_home.ToHomePage.run') as home:
            report = ActivityDaily(self.robot(config)).run(False, True)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual([a['type'] for a in report['activities']], ['collaboration_raid', 'revival', 'story'])
        self.assertEqual([s[0] for s in seen], ['CollaborationRaid', 'RevivalEvent', 'StoryEvent'])
        self.assertEqual(seen[0][1]['max_tickets'], 3)
        self.assertFalse(seen[2][1]['exchange'])
        self.assertEqual(seen[2][2], (False, True))
        self.assertEqual(len({s[1]['output'] for s in seen}), 3)
        self.assertEqual(home.call_count, 2)
        self.assertEqual(config, original)
        self.assertEqual(json.loads((self.root/'report.json').read_text()), report)

    def test_unavailable_revival_does_not_hide_live_collaboration(self):
        config = dict(Activities=dict(types=['revival', 'collaboration_raid']))
        with patch('pcrscript.news.fetch_event_news', return_value=EventNews()), \
             patch.object(CollaborationRaid, 'run', return_value=dict(status='complete')) as run:
            report = ActivityDaily(self.robot(config)).run()
        run.assert_called_once()
        self.assertEqual([r['status'] for r in report['activities']], ['unavailable', 'complete'])

    def test_verified_local_schedule_skips_closed_types_without_ui(self):
        event = Event(0, 10**12, 'Synthetic raid')
        news = EventNews(collaborationRaid=event, source=dict(provider='game_cdn', version='synthetic'))
        robot = self.robot({})
        robot._event_news = news
        with patch('pcrscript.news.fetch_event_news') as fetch, \
             patch.object(CollaborationRaid, 'run', return_value=dict(status='complete')) as raid, \
             patch.object(CampaignClean, 'run') as story, \
             patch.object(RevivalEventOnce, 'run') as revival:
            report = ActivityDaily(robot).run()
        fetch.assert_not_called()
        raid.assert_called_once()
        story.assert_not_called()
        revival.assert_not_called()
        self.assertEqual([a['status'] for a in report['activities']], ['complete','unavailable','unavailable'])
        self.assertEqual(report['database']['version'], 'synthetic')

    def test_pending_child_stops_other_types_without_navigation(self):
        with patch('pcrscript.news.fetch_event_news', return_value=EventNews()), \
             patch.object(CollaborationRaid, 'run', return_value=dict(status='partial', pending=['receipt unknown'])), \
             patch.object(CampaignClean, 'run') as story, \
             patch('pcrscript.tasks.task_home.ToHomePage.run') as home:
            report = ActivityDaily(self.robot(dict(Activities=dict(types=['collaboration_raid', 'story'])))).run()
        self.assertEqual(report['status'], 'partial')
        self.assertIn('receipt unknown', report['pending'][0])
        story.assert_not_called()
        home.assert_not_called()

    def test_legacy_story_substep_does_not_dispatch_other_types(self):
        with patch.object(CampaignClean, 'run', return_value=dict(status='complete')) as story, \
             patch.object(CollaborationRaid, 'run') as raid, \
             patch('pcrscript.news.fetch_event_news') as news:
            ActivityDaily(self.robot({})).run(only='missions')
        story.assert_called_once_with(True, False, only='missions')
        raid.assert_not_called()
        news.assert_not_called()

    def test_bad_type_or_nested_budget_fails_before_connecting(self):
        for options in (dict(types=['unknown']), dict(types=['story', 'story']),
                        dict(types='story'), dict(options=dict(story=False)), dict(first_clear=True)):
            with self.assertRaises(ValueError):
                activity_options(dict(Activities=options))
        config = dict(Activities=dict(types=['collaboration_raid'],
                      options=dict(collaboration_raid=dict(max_tickets=True))))
        with patch('pcrscript.runtime.load_config', return_value=config), \
             patch('pcrscript.runtime.robot_from_config') as connect:
            with self.assertRaises(ValueError):
                run_task_from_config('synthetic.yml', 'campaign_clean')
        connect.assert_not_called()

    def test_empty_types_skips_device_and_legacy_alias_still_runs_independently(self):
        with patch('pcrscript.runtime.load_config', return_value=dict(Activities=dict(types=[]))), \
             patch('pcrscript.runtime.robot_from_config') as connect:
            result = run_task_from_config('synthetic.yml', 'campaign_clean')
        self.assertEqual(result['status'], 'unavailable')
        connect.assert_not_called()
        rows = [['collaboration_raid']]
        modify_task_list(EventNews(), rows)
        self.assertEqual(rows, [['collaboration_raid']])

    def test_legacy_rows_are_deduplicated_only_when_covered_by_unified_entry(self):
        rows = [['revival_event_once'], ['collaboration_raid'], ['campaign_clean', False, True]]
        modify_task_list(EventNews(), rows)
        self.assertEqual(rows, [['campaign_clean', False, True]])
        rows = [['collaboration_raid'], ['campaign_clean']]
        modify_task_list(EventNews(), rows, dict(Activities=dict(types=['story'])))
        self.assertEqual(rows, [['collaboration_raid'], ['campaign_clean']])
        self.assertIs(find_taskclass('campaign_clean'), ActivityDaily)
        self.assertIs(find_taskclass('collaboration_raid'), CollaborationRaid)
