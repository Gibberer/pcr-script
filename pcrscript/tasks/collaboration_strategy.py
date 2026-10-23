"""Source scope and audited parties for the supported CN collaboration raid."""
import re

from .strategy_inputs import declared_region, source_statements
from .recollection_strategy import parties_for_floor, RecollectionFormation
from ..game_ui.screen import normalized

TITLE = '僵尸乐园连结'
BOSS = '佐贺陶洛斯'
DIFFICULTIES = ('普通', '困难', '高难')


def difficulty_scope(text):
    text = normalized(text)
    values = set()
    for name, pattern in (('高难', r'高难|VERYHARD|(?<![A-Za-z])VH(?![A-Za-z])'),
                          ('困难', r'(?<!VERY)HARD|困难'), ('普通', r'NORMAL|普通')):
        if re.search(pattern, text, re.I):
            values.add(name)
    return dict(boss=BOSS, difficulty=values.pop()) if len(values) == 1 else {}


def queries(options):
    return ['公主连结 国服 佐贺 讨伐', '公主连结 僵尸乐园连结 全自动',
            '公主连结 '+BOSS+' '+options['difficulty']]


def source_rejection(source, options):
    text = '\n'.join(t for t, _ in source_statements(source))
    if not any(word in text for word in (TITLE, BOSS, '佐贺联动', '佐贺偶像')):
        return '来源未确认本次联动身份'
    if not re.search(r'攻略|作业|打法|阵容|配置|全SET|一刀', text, re.I):
        return '来源没有首领攻略内容标识'
    if declared_region(text) not in ('unknown', 'cn'):
        return '来源明确服区不符或冲突'
    published = source.get('published_at', source.get('pubdate'))
    if type(published) not in (int, float) or not options['period_start']-7*86400 <= published < options['period_end']:
        return '来源发布时间不属于本期联动'
    if source.get('comment_complete') is False or source.get('comment_pending'):
        return '作者补充未读取完整'
    if any(row.get('images') for row in source.get('author_comments', [])):
        return '作者补充含尚未解析的图片'
    return None


def source_options(options, period):
    result = dict(options.get('sources', {}))
    result.update(task_type='collaboration', region='cn', area=TITLE,
                  aliases=[BOSS, '佐贺联动', '佐贺偶像'], category_terms=[], stage='',
                  difficulty='高难', period_start=period[0], period_end=period[1],
                  source_urls=options['source_urls'], search=options['discover_sources'],
                  skip_manual_media=True)
    result.setdefault('max_videos', 8)
    result.setdefault('max_pages_per_video', 12)
    result.setdefault('max_frames_per_page', 96)
    result.setdefault('max_video_seconds', 600)
    result.setdefault('parse_timeout', 1800)
    result.setdefault('media_quality', 16)
    return result


def combat_scope(texts):
    from ..game_ui.guide_vision import combat_boss_labels
    names = combat_boss_labels(texts)
    header = [normalized(t.text) for t in texts if t.score >= .95 and t.center[1] < 115]
    hp = health_values(header)
    if (len(names) != 1 or next(iter(names))[0] != BOSS or len(hp) != 1
            or not any(re.fullmatch(r'\d{1,2}:[0-5]\d', t) for t in header)):
        return {}
    return dict(boss=BOSS, level=next(iter(names))[1], maximum_hp=hp.pop())


def health_values(labels):
    return {maximum for _, maximum in health_pairs(labels) if maximum < 10**12}


def health_pairs(labels):
    values = set()
    for text in labels:
        if re.fullmatch(r'\d[\d,.]*/\d[\d,.]*', text):
            current, maximum = text.split('/')
            if all(re.fullmatch(r'\d+|\d{1,3}(?:[,.]\d{3})+', t) for t in (current, maximum)):
                current, maximum = (int(re.sub('[,.]', '', t)) for t in (current, maximum))
                if 0 <= current <= maximum < 10**15:
                    values.add((current, maximum))
    return values


def detail_scope(texts):
    from dataclasses import replace
    from ..game_ui.guide_vision import combat_boss_labels
    labels = {normalized(t.text) for t in texts if t.score >= .95}
    if not {'难度变更', '模拟战', '实战', '推荐玩家等级'} <= labels:
        return {}
    names = combat_boss_labels([replace(t, rectangle=(t.rectangle[0], t.rectangle[1]-320,
                            t.rectangle[2], t.rectangle[3])) for t in texts if 320 <= t.center[1] <= 390])
    hp = health_values([normalized(t.text) for t in texts if t.score >= .95 and 415 <= t.center[1] <= 470])
    scopes = [difficulty_scope(t.text) for t in texts if t.score >= .95 and t.center[0] < 450 and t.center[1] < 120]
    scopes = [s for s in scopes if s]
    if len(names) != 1 or next(iter(names))[0] != BOSS or len(hp) != 1 or len(scopes) != 1:
        return {}
    return dict(scopes[0], level=next(iter(names))[1], maximum_hp=hp.pop())


def parties_for_difficulty(report, difficulty, *, allow_local_trials, target=None):
    result = []
    for raw in report.get('parties', []):
        scope = raw.get('scope', {})
        actual = scope.get('difficulty')
        if raw.get('task_type') != 'collaboration' or scope.get('boss') != BOSS:
            continue
        exact_enemy = (target is not None and all(type(scope.get(k)) is int and scope[k] == target[k]
                                                 for k in ('level', 'maximum_hp')))
        stronger_enemy = (target is not None and all(type(scope.get(k)) is int and scope[k] >= target[k]
                                                    for k in ('level', 'maximum_hp')))
        numeric = all(type(scope.get(k)) is int for k in ('level', 'maximum_hp'))
        if target is not None and numeric and ((actual == difficulty and not exact_enemy)
                                               or actual != difficulty and not stronger_enemy):
            continue
        named = actual in DIFFICULTIES and DIFFICULTIES.index(actual) >= DIFFICULTIES.index(difficulty)
        if not named and not (allow_local_trials and (exact_enemy or stronger_enemy)):
            continue
        if actual != difficulty and not allow_local_trials:
            continue
        # The live first-clear detail supplies the difficulty name. Preserve
        # the original numeric source identity instead of relabelling it.
        number = DIFFICULTIES.index(difficulty)+1
        adapted = dict(raw, scope=dict(area=TITLE, floor=number))
        parties = parties_for_floor(dict(parties=[adapted]), TITLE, number,
                                    allow_local_trials=allow_local_trials)
        for party in parties:
            if actual != difficulty:
                party.build_basis = 'local_trial'
                party.assumptions.append(f'来源目标{scope}；仅在{difficulty}免费首通试打，不继承伤害或改写来源难度')
            result.append(party)
    return result


class CollaborationFormation(RecollectionFormation):
    """Use the standard event layout and preserve all declared build fields."""


class ScopeContext:
    """Bind a detail to a continuous fight without inheriting unknown frames."""
    def __init__(self):
        self.scope, self.maximum, self.timer = {}, None, None
        self.at = float('-inf')
        self.preparation_at = float('-inf')
        self.total_hp = None
        self.health = None
        self.health_offset = None
        self.detail_proof = None
        self.started = False

    def resolve(self, scope, verified, texts, seconds, combat, proof, *, loading=False):
        labels = [normalized(t.text) for t in texts if t.score >= .95]
        maxima = health_values(labels)
        maximum = next(iter(maxima)) if len(maxima) == 1 else None
        pairs = health_pairs(labels)
        totals = {p for p in pairs if p[1] >= 10**12}
        total = next(iter(totals)) if len(totals) == 1 else None
        health = next((current for current, limit in pairs if limit == maximum), None)
        timers = {int(m[1])*60+int(m[2]) for t in labels if (m := re.fullmatch(r'(\d{1,2}):([0-5]\d)', t))}
        timer = next(iter(timers)) if len(timers) == 1 else None
        if scope:
            if verified and scope == self.scope and total is None and seconds-self.at <= 2:
                total = self.total_hp
            self.scope = dict(scope) if verified else {}
            self.maximum, self.timer, self.at = maximum, timer, seconds
            self.total_hp, self.health = total, health
            self.health_offset = total[0]-health if total is not None and health is not None else None
            self.detail_proof = dict(proof)
            self.started = False
            return scope, verified, None
        from ..game_ui.guide_vision import combat_boss_labels
        boss = {name for name, _ in combat_boss_labels(texts)}
        header_pairs = health_pairs([normalized(t.text) for t in texts if t.score >= .95 and t.center[1] < 125])
        header_bars = (len(header_pairs) == 2 and any(p[1] >= 10**12 for p in header_pairs)
                       and any(p[1] == self.maximum for p in header_pairs))
        hud = '战斗' in labels and '合计' in labels or header_bars
        # This raid removes the boss name in combat but retains TWO health
        # bars. The exact global-current snapshot binds a fight to its detail;
        # local health must never increase into another attempt. A readable
        # clock additionally constrains continuity, but is often under ads.
        same_bars = (total is not None and self.total_hp is not None and total[1] == self.total_hp[1]
                     and health is not None and self.health_offset is not None
                     and total[0]-health == self.health_offset
                     and self.health is not None and health <= self.health)
        continuous = (self.scope and maximum == self.maximum and maximum is not None
                      and (timer is not None and boss == {BOSS} or not boss and hud and same_bars)
                      and seconds-self.at <= (8 if self.started else 15)
                      and (self.timer is None or timer is None or 0 <= self.timer-timer <= seconds-self.at+2))
        if (combat or hud) and continuous:
            self.at, self.timer = seconds, timer
            self.health = health
            self.started = True
            return dict(self.scope), True, dict(proof, method='collaboration_detail_to_combat',
                detail=self.detail_proof, health_offset=self.health_offset)
        preparation = ('队伍编组' in labels and ('战斗开始' in labels or '当前的成员' in labels)
                       or {'特别装备设定', '可变更队伍角色的特别装备。', '自动装备', '装备确定'} <= set(labels))
        if preparation and not self.started and seconds-self.at <= 15:
            self.preparation_at = seconds
        known_loading = (not self.started and any('加载中' in t or '正在进行数据连接' in t for t in labels)
                         or preparation and not self.started and seconds-self.at <= 15
                         or loading and seconds-self.preparation_at <= 2 and seconds-self.at <= 15
                         or (hud and maximum == self.maximum or combat) and seconds-self.at <= 8)
        if not known_loading:
            self.scope, self.maximum, self.timer = {}, None, None
        return {}, False, None
