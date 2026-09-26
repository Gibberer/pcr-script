"""Account-scoped, durable trial history, including interrupted attempts."""
from hashlib import sha256
import json
from pathlib import Path
import time
from uuid import uuid4

from ..run_session import atomic_json


def team_key(names):
    return '|'.join(sorted(names))


def previous_stage_key(stage):
    if stage.number > 1:
        return f'{stage.chapter}-{stage.number-1}'
    return f'{stage.chapter-1}-10' if stage.chapter > 1 else None


class AbyssHistory:
    def __init__(self, directory='cache/game/strategies/abyss_history', account='default'):
        self.path = Path(directory)/(sha256(account.encode()).hexdigest()[:20]+'.json')
        self.data = {'version': 1, 'stages': {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if self.data.get('version') != 1 or not isinstance(self.data.get('stages'), dict):
                raise ValueError('深域尝试历史格式不符，不能忽略已有失败记录')
        self.previously_failed = {k for k,v in self.data['stages'].items()
                                  if any(t.get('progressed') is not True for t in v)}

    @staticmethod
    def key(stage):
        return stage.element+'/'+stage.key

    def trials(self, stage):
        return self.data['stages'].get(self.key(stage), [])

    def failed_teams(self, stage):
        return {team_key(t['order']) for t in self.trials(stage) if t.get('progressed') is not True}

    def budget(self, stage, first, repeat):
        spent=sum(t.get('progressed') is not True for t in self.trials(stage))
        return max(0,min(repeat if self.key(stage) in self.previously_failed else first,
                         first-spent))

    def reconcile_previous_win(self, stage, remaining):
        """Confirm an interrupted win from the new NEXT and one spent attempt."""
        prior=previous_stage_key(stage)
        if prior is None or type(remaining) is not int:
            return None
        trials=self.data['stages'].get(stage.element+'/'+prior, [])
        if not trials:
            return None
        trial=trials[-1]
        if trial.get('progressed') is not None or trial.get('outcome')!='in_flight':
            return None
        path=Path(trial.get('report',''))
        try:
            report=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError,TypeError):
            return None
        if not isinstance(report,dict):
            return None
        match=next((battle for battle in report.get('battles',[])
                    if isinstance(battle,dict) and battle.get('history_id')==trial.get('id')),None)
        old=match.get('stage',{}) if isinstance(match,dict) else {}
        if not isinstance(old,dict):
            return None
        if (old.get('element')!=stage.element or f"{old.get('chapter')}-{old.get('number')}"!=prior
                or match.get('outcome')!='settled'
                or type(match.get('before_remaining')) is not int
                or match['before_remaining']-remaining!=1):
            return None
        trial.update(outcome='settled',progressed=True,after_remaining=remaining,
                     finished_at=time.time(),reconciliation='当前NEXT前进且挑战次数减少一，结合上轮已结束战斗报告')
        self.save()
        return dict(stage=stage.element+'/'+prior,history_id=trial['id'],
                    prior_report=str(path),before_remaining=match['before_remaining'],
                    after_remaining=remaining,next=stage.key)

    def start(self, stage, audit, report):
        trial = dict(id=uuid4().hex, started_at=time.time(), order=audit['order'],
                     formation=audit, outcome='in_flight', progressed=None, report=str(report))
        self.data['stages'].setdefault(self.key(stage), []).append(trial)
        self.save()
        return trial

    def finish(self, trial, battle):
        trial.update({k:v for k,v in battle.items() if k not in ('formation','stage')})
        trial['finished_at'] = time.time()
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(self.path, self.data)
