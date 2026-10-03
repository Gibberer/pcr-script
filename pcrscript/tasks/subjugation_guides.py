"""Current-event public guides: exact visible stages and audited trial seeds."""
from __future__ import annotations

from datetime import datetime
import re

from .event_strategy import EventParty, MemberRequirement
from .strategy_document import missing_fields, to_event_party
from ..constants import SERVER_TIMEZONE
from ..game_ui.screen import normalized

ELEMENTS = ('fire', 'water', 'wind', 'light', 'dark')
LABELS = ('火', '水', '风', '光', '暗')


def source_options(options, event, *, kind='outpost', difficulty='高难', boss='', boss_number=None):
    talent = event.extras.get('talent_id')
    if type(talent) is not int or talent not in range(1, 6):
        raise ValueError('本期加成属性未知，不能取得攻略')
    result = dict(options.get('sources', {}))
    result.update(task_type='subjugation', region='cn', area=event.extras['title'],
                  aliases=['深渊讨伐战', '深域讨伐战'], category_terms=[], stage='',
                  element=ELEMENTS[talent-1], kind=kind, difficulty=difficulty, boss=boss,
                  boss_number=boss_number,
                  event_id=event.extras['abyss_id'], period_start=event.startTimestamp,
                  period_end=event.endTimestamp, search=options.get('discover_sources', True),
                  source_urls=options.get('source_urls') or result.get('source_urls', []),
                  skip_manual_media=True, skip_long_media=True)
    result.setdefault('max_videos', 4)
    result.setdefault('max_pages_per_video', 4)
    result.setdefault('max_frames_per_page', 36)
    result.setdefault('max_video_seconds', 600)
    result.setdefault('parse_timeout', 300 if kind == 'boss' else 1800)
    result.setdefault('max_download_seconds', 180)
    return result


def queries(options):
    start = datetime.fromtimestamp(options['period_start'], SERVER_TIMEZONE)
    label = LABELS[ELEMENTS.index(options['element'])]
    target = '前哨 高难' if options['kind'] == 'outpost' else options['boss']
    return [f'公主连结 {start.month}月 深渊讨伐战 {label}',
            f'公主连结 {options["area"]}',
            f'公主连结 {start.year} {start.month}月 深渊讨伐战 {target}',
            f'公主连结 深渊讨伐战 {target} {label}']


def source_rejection(source, options):
    text = source.get('title', '')+' '+source.get('description', source.get('desc', ''))
    if not re.search(r'深[渊淵域]讨伐战|深淵討伐戰', text):
        return '来源没有确认深渊讨伐战玩法'
    published = source.get('published_at', source.get('pubdate'))
    if (type(published) not in (int, float)
            or not options['period_start']-7*86400 <= published < options['period_end']):
        return '来源发布时间不属于本期活动，未沿用旧期队伍'
    start = datetime.fromtimestamp(options['period_start'], SERVER_TIMEZONE)
    dates = re.findall(r'(20\d{2}|\d{2})\s*[年./-]\s*(\d{1,2})(?:月|[./-]|\b)', text)
    if any((int(y) if len(y) == 4 else 2000+int(y), int(m)) != (start.year, start.month)
           for y, m in dates):
        return '来源标注的年月与本期不符'
    months = re.findall(r'(?<!\d)(\d{1,2})月', text)
    if months and any(int(m) != start.month for m in months):
        return '来源月份与本期不符'
    declared = {ELEMENTS[i] for i, label in enumerate(LABELS)
                if re.search(re.escape(label)+r'(?:属性|深[渊域])|[\[【]'+re.escape(label)+r'[\]】]', text)}
    if declared and declared != {options['element']}:
        return '来源加成属性与本期不符'
    return None


def page_scope(title):
    difficulty = next((d for d in ('普通', '困难', '高难') if d in title), None)
    if not difficulty and re.search(r'(?<![A-Za-z])EX(?![A-Za-z])', title, re.I):
        difficulty = '高难'
    if not difficulty:
        return {}
    if re.search(r'前哨', title):
        return dict(kind='outpost', difficulty=difficulty)
    return {}


def choose_pages(source, options):
    pages = source.get('pages', [])
    if options['kind'] == 'outpost':
        return [p for p in pages if re.search(r'前哨', p.get('part', p.get('title', '')))] or (
            pages if len(pages) == 1 else [])
    boss = options['boss']
    exact = [p for p in pages if boss in p.get('part', p.get('title', ''))]
    # Numbered Boss parts are candidates only; their frames must prove the name.
    number = options.get('boss_number')
    numbered = [p for p in pages if type(number) is int and 1 <= number <= 3
        and re.search(r'Boss\s*'+str(number)+r'\b|(?<!\d)'+str(number)+r'\s*王|首领\s*'+str(number)+r'\b',
                      p.get('part', p.get('title', '')), re.I)]
    return exact or numbered or [p for p in pages if re.search(r'Boss|首领|王', p.get('part', p.get('title', '')), re.I)] or (
        pages if len(pages) == 1 else [])


def visible_scope(texts, page, options):
    metadata = page_scope(page.get('part', page.get('title', '')))
    labels = [t.text.replace(' ', '') for t in texts if t.score >= .94]
    header = [t.text.replace(' ', '') for t in texts if t.score >= .94
              and t.rectangle[1]+t.rectangle[3]/2 < 170]
    difficulty = {d for d in ('普通', '困难', '高难', '极难') if any(d in label for label in header)}
    found = {}
    if len(difficulty) == 1:
        if any('前哨关卡' in label for label in header):
            found = dict(kind='outpost', difficulty=next(iter(difficulty)))
        elif (options.get('boss') and any('BOSS详情' in label for label in header)
              and any(re.fullmatch(re.escape(options['boss'])+r'(?:(?:等级[.．:：]?|Lv\.?)[1-9]\d*)?', label, re.I)
                      for label in labels)):
            found = dict(kind='boss', difficulty=next(iter(difficulty)), boss=options['boss'])
    if metadata and found and metadata != found:
        return {'conflict': True}, False
    return (found, True) if found else (metadata, bool(metadata))


def damage_reference(page, scope, maximum, source):
    """Use the verified plan's own title, never another Boss's advertised damage."""
    if scope.get('kind') != 'boss':
        return {}
    title = page.get('part', page.get('title', ''))
    amounts = {int(float(m[1]) * (100000000 if m[2] == '亿' else 10000))
               for m in re.finditer(r'(?<![\d.])(\d+(?:\.\d+)?)\s*(亿|万)', title)}
    cut_values = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
                  '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    cuts = {int(m[1]) if m[1].isdigit() else cut_values[m[1]]
            for m in re.finditer(r'(?<!\d)([1-9]\d*|[一二两三四五六七八九十])\s*刀', title)}
    if len(amounts) > 1 or len(cuts) > 1:
        return {}
    cut = next(iter(cuts), None)
    damage = next(iter(amounts), None)
    if damage is None and cut and maximum:
        damage = (maximum+cut-1)//cut
    if damage is None or damage <= 0:
        return {}
    return dict(damage=damage, cuts=cut, max_hp=maximum, scope=dict(scope),
                evidence=[dict(source=source, cid=page['cid'], method='part_title', text=title)])


def relevant_statements(text, options):
    """Keep common requirements and those explicitly scoped to this target."""
    result = []
    for line in text.splitlines():
        marker = re.match(r'\s*(?:[【\[]\s*)?(?:Boss\s*([1-3])|([1-3])\s*王)', line, re.I)
        if marker and (options['kind'] == 'outpost' or options.get('boss_number') is not None
                       and int(marker[1] or marker[2]) != options['boss_number']):
            continue
        if re.match(r'\s*(?:[【\[]\s*)?前哨', line) and options['kind'] == 'boss':
            continue
        result.append(line)
    return '\n'.join(result)


class ScopeContext:
    """Bind a visible detail to one uninterrupted battle; never inherit a tier."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.scope, self.proof, self.timer, self.maximum = {}, None, None, None
        self.detail_at = float('-inf')
        self.combat_at = None

    def resolve(self, scope, verified, texts, seconds, combat, proof):
        labels = [t.text.replace(' ', '') for t in texts if t.score >= .94]
        timers = {int(m[1])*60+int(m[2]) for text in labels
                  if (m := re.fullmatch(r'(\d{1,2}):(\d{2})', text)) and int(m[2]) < 60}
        timer = next(iter(timers)) if len(timers) == 1 else None
        maxima = {int(m[2]) for text in labels
                  if (m := re.fullmatch(r'(\d{7,11})/(\d{7,11})', re.sub('[,，]', '', text)))}
        maximum = next(iter(maxima)) if len(maxima) == 1 else None
        if scope:
            self.reset()
            if verified:
                self.scope, self.proof, self.maximum = scope, proof, maximum
                self.detail_at, self.timer = seconds, timer if combat else None
            return scope, verified, None
        if any(re.search(r'WIN|战斗失败|伤害报告|下一步|前往深渊讨伐战', t, re.I) for t in labels):
            self.reset()
            return {}, False, None
        # A UB animation can hide the card row while the same boss HUD is
        # still visible. Require its exact identity, timer and HP maximum.
        boss = self.scope.get('boss')
        if (boss and self.timer is not None and timer is not None and maximum == self.maximum
                and any(label == boss or re.fullmatch(re.escape(boss)+r'(?:等级[.．:：]?|Lv\.?)[1-9]\d*', label, re.I)
                        for label in labels)):
            combat = True
        if combat:
            if (not self.scope or self.timer is None and seconds-self.detail_at > 15
                    or self.combat_at is not None and seconds-self.combat_at > 8
                    or timer is not None and self.timer is not None and timer > self.timer
                    or self.scope.get('kind') == 'boss' and maximum is not None and maximum != self.maximum):
                self.reset()
                return {}, False, None
            # Effects can hide the HUD for a sample. Do not authorize that
            # frame, but allow the next continuous, fully observed HUD.
            if timer is None or self.scope.get('kind') == 'boss' and maximum is None:
                return {}, False, None
            self.timer = timer
            self.combat_at = seconds
            return dict(self.scope), True, dict(self.proof, method='subjugation_detail_to_combat')
        formation = ('队伍编组' in labels or ('特别装备设定' in labels
                     and '可变更队伍角色的特别装备。' in labels))
        if (formation and self.scope and self.timer is None
                and seconds-self.detail_at <= 15):
            return dict(self.scope), True, dict(self.proof, method='subjugation_detail_to_formation')
        if not any(re.search(r'加载中|正在进行数据连接', t) for t in labels):
            self.reset()
        return {}, False, None


def parties_for_target(report, options, *, allow_local_trials):
    result = []
    wanted = dict(kind=options['kind'], difficulty=options['difficulty'])
    if wanted['kind'] == 'boss':
        wanted['boss'] = options['boss']
    for raw in report.get('parties', []):
        higher_trial = (allow_local_trials and raw.get('scope') != wanted and wanted.get('kind') == 'boss'
            and raw.get('scope') == dict(kind='boss', difficulty='极难', boss=options['boss']))
        members = raw.get('members', [])
        names = [m.get('name') for m in members]
        flags = [raw.get('auto', {})]+[m.get('instant', {}) for m in members]
        if ((raw.get('scope') != wanted and not higher_trial) or not raw.get('scope_verified')
                or raw.get('region') != 'cn' or raw.get('target_region') != 'cn'
                or raw.get('global_requirements') or raw.get('manual_actions')
                or len(names) != 5 or any(not isinstance(n, str) or not n or n.startswith('unit:') for n in names)
                or len(set(map(normalized, names))) != 5
                or any(type(f.get('value')) is not bool or not f.get('evidence') or f.get('conflicts') for f in flags)
                or any(m.get(k, {}).get('conflicts') for m in members
                       for k in ('level', 'rank', 'stars', 'skill_level', 'unique', 'unique2', 'unique_level', 'unique2_stars'))):
            continue
        missing = missing_fields(raw)
        if not missing and not higher_trial:
            candidate = to_event_party(raw)
        elif allow_local_trials:
            candidate = EventParty(raw['id']+'-trial', raw['source'],
                [MemberRequirement(m['name'], m.get('level', {}).get('value'),
                    m.get('rank', {}).get('value'), m.get('stars', {}).get('value'),
                    m.get('unique', {}).get('value'), m.get('unique2', {}).get('value'),
                    m['instant']['value'], m.get('skill_level', {}).get('value'),
                    unique_level=m.get('unique_level', {}).get('value'),
                    unique2_stars=m.get('unique2_stars', {}).get('value'))
                 for m in members], max_attempts=1, build_basis='local_trial',
                assumptions=missing, auto=raw['auto']['value'])
        else:
            continue
        if higher_trial:
            candidate.assumptions.append('同名首领极难来源阵容用于当前难度账号试打，保留来源难度，先免费模拟再核验实战')
        candidate.damage_reference = dict(raw.get('damage_reference', {}))
        result.append(candidate)
    return result
