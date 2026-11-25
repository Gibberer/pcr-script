"""One public activity entry; editions and combat rules stay in their handlers."""
from copy import copy, deepcopy
from pathlib import Path

from .base import TimeLimitTask
from .registry import register
from ..run_session import atomic_json, checkpoint, RunCancelled

ACTIVITY_SECTIONS = {'collaboration_raid': 'CollaborationRaid', 'revival': 'RevivalEvent', 'story': 'StoryEvent'}
DEFAULT_TYPES = tuple(ACTIVITY_SECTIONS)
LEGACY_TYPES = {'collaboration_raid': 'collaboration_raid', 'revival_event_once': 'revival'}


def activity_options(config):
    value = deepcopy(config.get('Activities', {}))
    if not isinstance(value, dict):
        raise ValueError('Activities必须为对象')
    if set(value)-{'types', 'options', 'output'}:
        raise ValueError('Activities仅支持types、options；玩法选项请放入options.<type>或原配置段')
    types = value.setdefault('types', list(DEFAULT_TYPES))
    if (not isinstance(types, list) or any(not isinstance(t, str) or t not in ACTIVITY_SECTIONS for t in types)
            or len(types) != len(set(types))):
        raise ValueError('Activities.types必须为不重复的story、revival、collaboration_raid列表')
    options = value.setdefault('options', {})
    if (not isinstance(options, dict) or any(k not in ACTIVITY_SECTIONS or not isinstance(v, dict)
                                           for k, v in options.items())):
        raise ValueError('Activities.options必须按活动类型配置对象')
    return value


def handler_config(config, kind, options):
    result = deepcopy(config)
    section = ACTIVITY_SECTIONS[kind]
    existing = result.get(section, {})
    if not isinstance(existing, dict):
        raise ValueError(section+'必须为对象')
    result[section] = {**existing, **options['options'].get(kind, {})}
    return result


def unsettled(child) -> bool:
    """A battle, spend, claim or exchange journal awaits reconciliation."""
    state = getattr(child, 'state', None)
    return isinstance(state, dict) and any(str(k).startswith('pending_') and v for k, v in state.items())


@register('campaign_clean', requires_home=True)
class ActivityDaily(TimeLimitTask):
    config_section = 'Activities'

    @staticmethod
    def valid(event_news, args=None):
        # Closed types are skipped per schedule in run(); each handler still
        # verifies its live entrance, event identity and full period.
        return ActivityDaily, args

    @classmethod
    def prepare(cls, config, *args, **kwargs):
        options = activity_options(config)
        if not options['types'] and kwargs.get('only', 'all') == 'all':
            return args, kwargs, dict(status='unavailable', activities=[], pending=[])
        if 'collaboration_raid' in options['types'] and kwargs.get('only', 'all') == 'all':
            from .task_collaboration_raid import CollaborationRaid
            CollaborationRaid.prepare(handler_config(config, 'collaboration_raid', options))
        return args, kwargs, None

    def run(self, hard_chapter=True, exhaust_power=False, *, only='all'):
        from .task_story_event import CampaignClean
        from .task_revival_event import RevivalEventOnce
        from .task_collaboration_raid import CollaborationRaid
        from .task_home import ToHomePage
        from ..news import fetch_event_news

        config = getattr(self.robot, 'task_config', {})
        options = activity_options(config)
        types = options['types'] if only == 'all' else ['story']
        handlers = {'story': CampaignClean, 'revival': RevivalEventOnce, 'collaboration_raid': CollaborationRaid}
        root = Path(self.task_options().get('output', 'cache/daily/activities'))
        report = dict(status='running', activities=[], pending=[])
        previous_executed = False
        # Types are independent: one type's failure only stops the rest when
        # it leaves an unsettled battle/spend journal behind.
        deferred_error = None
        try:
            news = None
            if only == 'all':
                news = getattr(self.robot, '_event_news', None) or fetch_event_news()
                report['database'] = news.source
            for index, kind in enumerate(types):
                checkpoint()
                self.report_progress('活动日常 · '+kind, index, len(types))
                child_config = handler_config(config, kind, options)
                event = None
                field = {'collaboration_raid': 'collaborationRaid', 'revival': 'revival', 'story': 'hatsune'}[kind]
                if news is not None and news.source.get('provider') == 'game_cdn' and getattr(news, field) is None:
                    report['activities'].append(dict(type=kind, status='unavailable',
                                                     reason='已验证静态主库中没有进行中的日程'))
                    continue
                if kind == 'revival':
                    event = news.revival
                    if event is None:
                        report['activities'].append(dict(type=kind, status='unavailable'))
                        continue
                    args, _, skipped = RevivalEventOnce.prepare(child_config, event)
                    if skipped is not None:
                        report['activities'].append(dict(type=kind, **skipped))
                        continue
                    event = args[0]
                child_robot = copy(self.robot)
                child_robot.task_config = child_config
                child_robot._task_output = root/kind
                if previous_executed:
                    ToHomePage(self.robot).run(timeout=60)
                    previous_executed = False
                child = handlers[kind](child_robot)
                try:
                    if kind == 'story':
                        result = child.run(hard_chapter, exhaust_power, only=only)
                    elif kind == 'revival':
                        result = child.run(event)
                    else:
                        result = child.run()
                except RunCancelled:
                    raise
                except Exception as error:
                    report['activities'].append(dict(type=kind, status='error', pending=[str(error)]))
                    report['pending'].append(kind+'：'+str(error))
                    atomic_json(root/'report.json', report)
                    if unsettled(child):
                        raise
                    deferred_error = deferred_error or error
                    previous_executed = True  # Return home before the next type.
                    continue
                status = result.get('status', 'finished')
                report['activities'].append(dict(type=kind, status=status, report=result))
                atomic_json(root/'report.json', report)
                if status not in ('complete', 'already_complete', 'unavailable'):
                    report['pending'].extend(kind+'：'+str(reason) for reason in result.get('pending', []))
                    if unsettled(child):
                        report['status'] = 'partial'
                        report['pending'].append('本类型有未核账记录，保留现场；其余类型留待接续')
                        return report
                previous_executed = True
            if deferred_error is not None:
                raise deferred_error
            statuses = [a['status'] for a in report['activities']]
            if any(s not in ('complete', 'already_complete', 'unavailable') for s in statuses):
                report['status'] = 'partial'
            else:
                report['status'] = 'complete' if any(s in ('complete', 'already_complete')
                                                   for s in statuses) else 'unavailable'
            return report
        except RunCancelled:
            report['status'] = 'cancelled'
            raise
        except BaseException as error:
            report['status'] = 'error'
            report['pending'].append(str(error))
            raise
        finally:
            atomic_json(root/'report.json', report)
