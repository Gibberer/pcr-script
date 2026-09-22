"""Local source-backed dungeon plans and finite, ordered party selection."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import yaml
from .event_formation import EventFormation
from .event_strategy import EventParty, MemberRequirement
from ..game_ui.screen import EventUIError, normalized
from ..run_session import clock as time


class DungeonFormation(EventFormation):
    slots = [(96+109*i, 426) for i in range(5)]
    slot_top = 378
    search_top = 180
    defocus = (580, 356)

    def __init__(self, ui):
        super().__init__(ui)
        # Only current-process, read-only character-page evidence; never load
        # an old roster as permission to treat unknown badges as absent.
        self.unreleased = {}
        self.use_current_build = False

    @property
    def requires_declared_build(self):
        return not self.use_current_build

    def resolve_requirement(self, requirement, actual):
        if not self.use_current_build:
            return requirement
        # An explicitly authorized local trial may bind the *observed* build.
        # Minimums keep unknown/zero stats unready; unknown flags remain None.
        return MemberRequirement(requirement.name, max(actual.level or 1, 1),
            max(actual.rank or 1, 1), actual.stars or 1, actual.unique, actual.unique2,
            requirement.instant, max(actual.skill_level or 1, 1))

    def inspect(self, *args, **kwargs):
        actual = super().inspect(*args, **kwargs)
        proof = self.unreleased.get(normalized(actual.name))
        if (actual.identity_verified and actual.unique is None and actual.unique2 is None and proof
                and 0 <= time.time()-proof[0] < 300):
            actual.unique = actual.unique2 = False
            actual.equipment_evidence = proof[1]
            if kwargs.get('full', True):
                self.observed[normalized(actual.name)] = actual
                (self.ui.output/'roster.json').write_text(json.dumps(
                    {k: asdict(v) for k, v in self.observed.items()}, ensure_ascii=False, indent=2), encoding='utf-8')
        return actual

    def select(self, party):
        ready, details = super().select(party)
        details['observed'] = {m.name: asdict(self.observed[normalized(m.name)])
                               for m in party.members if normalized(m.name) in self.observed}
        if self.use_current_build:
            details['build_basis'] = 'local_trial_current_account'
        return ready, details

    def _select_by_scrolling(self, party: EventParty):
        raise EventUIError('地下城搜索栏未确认；未使用活动列表坐标回退')


@dataclass
class DungeonParty:
    key: str
    floor: int
    phase: str
    party: EventParty
    use_current_build: bool = False
    role: str = 'main'
    source_damage: int | None = None
    max_hp: int | None = None


def load_plan(path: str | Path, area: str, *, allow_local_trials: bool = False) -> list[DungeonParty]:
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1 or data.get('area') != area:
        raise ValueError('地下城方案版本或区域不符')
    result = []
    seen = set()
    for entry in data.get('parties', []):
        basis = entry.get('build_basis', 'source')
        if basis not in ('source', 'local_trial') or (basis == 'local_trial' and not allow_local_trials):
            raise ValueError('本地试验队伍需要本次显式开启 allow_local_trials')
        current = entry.get('use_current_build', False)
        if type(current) is not bool or (current and basis != 'local_trial'):
            raise ValueError('use_current_build 仅允许本次授权的 local_trial')
        key = entry['id']
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError('地下城队伍 id 必须唯一且非空')
        seen.add(key)
        floor = entry['floor']
        if type(floor) is not int or not 1 <= floor <= 5:
            raise ValueError('地下城队伍 floor 必须为1到5')
        phase = entry.get('phase', '')
        if not isinstance(phase, str) or (floor == 5 and not phase):
            raise ValueError('首领队伍必须明确适用阶段')
        source = entry.get('source')
        if not isinstance(source, str) or not source.strip():
            raise ValueError('地下城队伍必须提供可追溯来源')
        members = []
        for raw in entry['members']:
            if current:
                if set(raw) != {'name', 'instant'} or not isinstance(raw['name'], str) or not raw['name'].strip() or type(raw['instant']) is not bool:
                    raise ValueError('按账号试打仅提供完整 name 和明确 instant；培养状态必须实时读取')
                members.append(MemberRequirement(raw['name'], 1, 1, 1, None, None, raw['instant']))
                continue
            # Missing equipment flags must never silently become False.
            for flag in ('unique', 'unique2', 'instant'):
                if type(raw.get(flag)) is not bool:
                    raise ValueError(f'必须明确 {flag} 开关')
            member = MemberRequirement(**raw)
            if not member.name or member.stars not in range(1, 7) or min(member.level, member.rank, member.skill_level) < 1:
                raise ValueError('角色名、星级、等级、Rank与技能等级必须明确')
            members.append(member)
        if len(members) != 5 or len({normalized(m.name) for m in members}) != 5:
            raise ValueError('每队必须有五名不同角色')
        deaths = entry.get('allow_deaths', 0)
        if type(deaths) is not int or not 0 <= deaths <= 5:
            raise ValueError('allow_deaths 必须为0到5')
        role = entry.get('role', 'main')
        if role not in ('main', 'bridge', 'cleanup', 'finisher'):
            raise ValueError('未知地下城队伍用途')
        for field in ('source_damage', 'max_hp'):
            value = entry.get(field)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f'{field} 必须为非负整数')
        result.append(DungeonParty(key, floor, normalized(phase),
                      EventParty(key, source, members, max_attempts=1, allow_deaths=deaths), current,
                      role, entry.get('source_damage'), entry.get('max_hp')))
    return result


def next_party(plan: list[DungeonParty], floor: int, text: str, used: set[str], hp: int | None = None) -> DungeonParty | None:
    text = normalized(text)
    return next((entry for entry in plan if entry.floor == floor and entry.key not in used
                 and (not entry.phase or entry.phase in text)
                 and (entry.max_hp is None or (hp is not None and hp <= entry.max_hp))), None)


def route_conflicts(plan: list[DungeonParty]) -> dict[str, list[str]]:
    """A committed boss route cannot spend the same character twice.

    Candidate alternatives belong in separate plans until one is selected.
    Ordinary floors may reuse surviving characters and are excluded here.
    """
    owners: dict[str, list[str]] = {}
    for entry in plan:
        if entry.floor == 5:
            for member in entry.party.members:
                owners.setdefault(normalized(member.name), []).append(entry.key)
    return {name: keys for name, keys in owners.items() if len(keys) > 1}
