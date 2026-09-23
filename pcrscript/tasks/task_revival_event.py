"""One completion per revival occurrence, selected by news and live UI layout."""
from __future__ import annotations
from .registry import register
import json
from typing import TYPE_CHECKING, Any
from .base import BaseTask, Event, EventNews, TaskOptions, TaskReport, TaskConfig, PreparedTask
if TYPE_CHECKING:
    from pcrscript import Robot
from pcrscript.run_session import clock as time

from .task_story_event import CampaignClean
from .revival_state import RevivalState
from ..game_ui.event_layout import event_layout, map_dialogue
from ..game_ui.screen import EventUIError


@register("revival_event_once")
class RevivalEventOnce(CampaignClean):
    config_section = "RevivalEvent"
    config_attribute = "revival_event_options"

    def __init__(self, robot: Robot, event: Event | None = None, options: TaskOptions | None = None) -> None:
        self.robot = robot
        options = self.task_options() if options is None else options
        options = {'output': 'cache/daily/revival_event', **(options or {})}
        super().__init__(robot, options)
        self.event = event
        self.layout = None
        self.state = None
        if event is not None:
            self.set_event(event)

    def set_event(self, event: Event) -> None:
        self.event = event
        options = self.options
        self.state = RevivalState(options.get('state_dir', 'cache/daily/revival_state'),
                                  options.get('account_key', getattr(self.robot.driver, 'index', 0)), event)
        self.report.update(event_id=event.extras['event_id'], event=event.name)
        if self.state.data.get('hard_trial_started'):
            self.report['hard_trial_started'] = True

    def enter(self) -> bool:
        # Always traverse the explicit revival entrance, even if another event
        # is already open. The calendar describes the edition, not the layout.
        s = self.ui.capture()
        if s.find('BOSS详情|队伍编组', (0,0,750,80)):
            self.ui.expect_click('取消', (250,420,950,525), exact=True)
            s = self.ui.capture()
        adventure = s.find('冒险', (460, 470, 600, 540), exact=True)
        if not adventure and s.find('我的主页|主菜单', (0, 470, 960, 540)):
            adventure = (532, 515)  # Verified shared bottom navigation.
        if not adventure:
            raise EventUIError('请先返回可见底栏的页面，再进入复刻活动')
        self.ui.click(adventure)
        for _ in range(15):
            s = self.ui.capture()
            if s.find('主线关卡', (45, 0, 240, 65), exact=True):
                self.ui.click((32, 30))
                continue
            entry = s.find('复刻', (0, 280, 465, 465), exact=True)
            if entry and s.find('主线关卡'):
                self.ui.save('revival_entry', s)
                self.ui.click(entry)
                break
            time.sleep(.5)
        else:
            raise EventUIError('活动情报有复刻，但冒险页未确认复刻入口')
        for _ in range(60):
            self.check_deadline()
            s = self.ui.capture()
            if map_dialogue(s):
                self.ui.click((775,495))
                continue
            if self.entry_dialog(s) or self.story_dialog(s):
                continue
            self.layout = event_layout(s)
            if self.layout:
                self.report['layout'] = self.layout
                self.ui.save('revival_home', s)
                return True
            time.sleep(.5)
        raise EventUIError('复刻入口后的页面布局无法识别')

    def run(self, event: Event | None = None) -> TaskReport:
        if event is not None or self.state is None:
            args, _, report = self.prepare({self.config_section: self.options}, event or self.event)
            if report is not None:
                self.report.update(report)
                return self.report
            self.set_event(args[0])
        if self.state.complete:
            self.report['status'] = 'already_complete'
            return self.report
        try:
            if not self.event.startTimestamp <= time.time() < self.event.endTimestamp:
                self.report['status'] = 'unavailable'
                return self.report
            self.enter()
            if self.layout == 'list':
                # Reuse the list workflow without re-entering the normal event.
                from .event_battle import EventBattles
                battles = EventBattles(self)
                battles.first_clear()
                battles.bosses()
                self.stories()
                self.memoirs()
                self.missions()
                self.exchange()
            else:
                from .revival_map import RevivalMap
                RevivalMap(self).run()
            self.report['status'] = 'partial' if self.report['pending'] else 'complete'
            return self.report
        except Exception as error:
            from pcrscript.run_session import failure
            failure(error)
            self.report['status'] = 'error'
            self.report['pending'].append(str(error))
            self.ui.save('error')
            raise
        finally:
            self.state.save(self.report)
            (self.ui.output / 'report.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')

    @classmethod
    def prepare(cls, config: TaskConfig, event: Event | None = None) -> PreparedTask:
        if event is None:
            from ..news import fetch_event_news
            event = fetch_event_news().revival
        if not event or not cls.event_valid(event):
            return (), {}, {'status': 'unavailable'}
        from .revival_state import RevivalState
        options = config.get(cls.config_section, {})
        account = options.get('account_key')
        if account is not None and RevivalState(options.get('state_dir', 'cache/daily/revival_state'), account, event).complete:
            return (), {}, {'status': 'already_complete', 'event_id': event.extras['event_id']}
        return (event,), {}, None


    @staticmethod
    def valid(event_news: EventNews, args: list[Any] | None = None) -> tuple[type[BaseTask], list[Any] | None] | None:
        event = event_news.revival
        if event and RevivalEventOnce.event_valid(event):
            return RevivalEventOnce, [event]
