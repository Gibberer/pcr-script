"""Account-scoped, durable trial history, including interrupted attempts."""
from hashlib import sha256
import json
from pathlib import Path
import time
from uuid import uuid4

from ..run_session import atomic_json


def team_key(names):
    return '|'.join(sorted(names))


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
        return repeat if self.key(stage) in self.previously_failed else first

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
