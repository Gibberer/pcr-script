"""Current-event public guides: exact visible stages and audited trial seeds."""
from __future__ import annotations

from datetime import datetime
import re

from .event_strategy import EventParty, MemberRequirement
from .strategy_document import missing_fields, to_event_party
from .strategy_inputs import declared_region, source_statements
from ..constants import SERVER_TIMEZONE
from ..game_ui.screen import normalized

ELEMENTS = ('fire', 'water', 'wind', 'light', 'dark')
LABELS = ('火', '水', '风', '光', '暗')
SHARED_REQUIREMENTS = re.compile(r'通用|共同|共用|公共|全局|所有|全部')
BOSS_LABEL = re.compile(r'Boss|首领|[1-3]\s*王', re.I)
BUILD_LABEL = re.compile(r'等级|(?<![A-Za-z])Lv|Rank|(?<![A-Za-z])R\s*\d|技能|专武|专用装备|专\s*\d|星级|星数|[0-9一二三四五六七八九十]+[星★]', re.I)
BUILD_VALUE = re.compile(
    r'(?:[1-6][星★]|(?:等级|Lv\.?|Rank|R|技能(?:等级)?)[：:=]?\d{1,3}(?!\d)|'
    r'专(?:用装备|武)?[12一二](?:强化)?(?:等级|阶段|Lv\.?)?[：:=]?'
    r'(?:\d{1,3}(?:[星★级])?|未开启|未装备|未实装|未开放|已装备|关闭|开启|装备|有|无)|'
    r'专[：:=]?\d{2,3}(?!\d))', re.I)


def source_options(options, event, *, kind='outpost', difficulty='高难', boss='', boss_number=None):
    talent = event.extras.get('talent_id')
    if type(talent) is not int or talent not in range(1, 6):
        raise ValueError('本期加成属性未知，不能取得攻略')
    result = dict(options.get('sources', {}))
    result.pop('observed_target', None)
    result.update(task_type='subjugation', region='cn', area=event.extras['title'],
                  aliases=['深渊讨伐战', '深域讨伐战'], category_terms=[], stage='',
                  element=ELEMENTS[talent-1], kind=kind, difficulty=difficulty, boss=boss,
                  boss_number=boss_number,
                  event_id=event.extras['abyss_id'], period_start=event.startTimestamp,
                  period_end=event.endTimestamp, search=options.get('discover_sources', True),
                  source_urls=options.get('source_urls') or result.get('source_urls', []),
                  skip_manual_media=True, skip_long_media=True)
    result.setdefault('max_videos', 4)
    result.setdefault('max_pages_per_video', 12)
    result.setdefault('max_frames_per_page', 96)
    result.setdefault('max_video_seconds', 600)
    result.setdefault('parse_timeout', 300 if kind == 'boss' else 1800)
    result.setdefault('max_download_seconds', 180)
    return result


def queries(options):
    start = datetime.fromtimestamp(options['period_start'], SERVER_TIMEZONE)
    label = LABELS[ELEMENTS.index(options['element'])]
    target = ('前哨' if options['kind'] == 'outpost' else options['boss'])+' '+options['difficulty']
    return [f'公主连结 {start.month}月 深渊讨伐战 {label}',
            f'公主连结 {options["area"]}',
            f'公主连结 {start.year} {start.month}月 深渊讨伐战 {target}',
            f'公主连结 深渊讨伐战 {target} {label}']


def source_rejection(source, options):
    text = '\n'.join(statement for statement, _ in source_statements(source))
    region = declared_region(text)
    if region not in ('unknown', options.get('region', 'cn')):
        return '来源服区与目标不符或声明冲突'
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
        and re.search(r'Boss\s*'+str(number)+r'(?!\d)|(?<!\d)'+str(number)+r'\s*王|首领\s*'+str(number)+r'(?!\d)',
                      p.get('part', p.get('title', '')), re.I)]
    return exact or numbered or [p for p in pages if re.search(r'Boss|首领|王', p.get('part', p.get('title', '')), re.I)] or (
        pages if len(pages) == 1 else [])


def requirement_pages(source, options):
    """Any page may carry conditions unless it explicitly targets another fight."""
    result = []
    for page in source.get('pages', []):
        title = page.get('part', page.get('title', ''))
        if title.strip() and not relevant_statements(title, options):
            continue
        result.append(page)
    return result


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
    amount = r'(?<![\d.])(\d+(?:\.\d+)?)\s*(亿|万)'
    amounts = {int(float(m[1]) * (100000000 if m[2] == '亿' else 10000))
               for m in re.finditer(amount, title)}
    damage_label = re.search(r'(?:伤害|输出)\s*[:：=]?\s*'+amount+'|'+amount+r'\s*(?:伤害|输出)', title)
    cut_values = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
                  '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    cuts = {int(m[1]) if m[1].isdigit() else cut_values[m[1]]
            for m in re.finditer(r'(?<!\d)([1-9]\d*|[一二两三四五六七八九十])\s*刀\s*(?:击杀|击破|打完|打死|收掉)', title)}
    if len(amounts) > 1 or len(cuts) > 1:
        return {}
    cut = next(iter(cuts), None)
    damage = next(iter(amounts), None) if damage_label else None
    if damage is None and cut and maximum:
        damage = (maximum+cut-1)//cut
    if damage is None or damage <= 0:
        return {}
    return dict(damage=damage, cuts=cut, max_hp=maximum, scope=dict(scope),
                evidence=[dict(source=source, cid=page['cid'], method='part_title', text=title)])


def leading_boss_scope(line):
    """Read a complete leading boss list/range; ambiguous scopes remain common."""
    atom = r'(?:(?:Boss|首领)\s*)?[1-3](?!\d)(?:\s*王)?'
    match = re.match(r'\s*[【\[]?\s*('+atom+r'(?:\s*[/、,，&和及与\-－~～至到]\s*'+atom+r')*)', line, re.I)
    if (not match or not re.search(r'Boss|首领|王', match[1], re.I) or '前哨' in line
            or re.match(r'\s*[/、,，&和及与\-－~～至到]', line[match.end():])
            or BOSS_LABEL.search(line[match.end():])):
        return None, 0
    markers = list(re.finditer(r'[1-3]', match[1]))
    bosses = {int(m[0]) for m in markers}
    for first, second in zip(markers, markers[1:]):
        if re.search(r'[\-－~～至到]', match[1][first.end():second.start()]):
            low, high = sorted((int(first[0]), int(second[0])))
            bosses.update(range(low, high+1))
    return bosses, match.end()


def relevant_statements(text, options):
    """Keep common requirements and those explicitly scoped to this target."""
    result = []
    # Lists use commas/slashes; sentence boundaries delimit independent scopes.
    # A remaining clause with later target markers is ambiguous, never unrelated.
    for line in re.split(r'[\r\n;；。!?！？|｜]+', text):
        line = line.strip()
        if not line:
            continue
        if SHARED_REQUIREMENTS.search(line):
            result.append(line)
            continue
        bosses, scope_end = leading_boss_scope(line)
        if options.get('boss') and options['boss'] in line[scope_end:]:
            bosses = None
        if bosses is not None and (options['kind'] == 'outpost' or options.get('boss_number') is not None
                                   and options['boss_number'] not in bosses):
            continue
        boss_label = BOSS_LABEL.search(line)
        if (options['kind'] == 'outpost' and '前哨' not in line
                and re.match(r'\s*[【\[]?\s*(?:Boss(?![A-Za-z0-9])|首领)(?!\s*[1-3])', line, re.I)):
            continue
        if re.match(r'\s*(?:[【\[]\s*)?前哨', line) and options['kind'] == 'boss' and not boss_label:
            continue
        result.append(line)
    return '\n'.join(result)


def metadata_build_requirements(metadata, options, names):
    """Bind only fully read named declarations; retain other build text as blocking evidence."""
    from ..game_ui.guide_vision import labeled_fields
    rows = []
    scopes = r'Boss[1-3](?!\d)|[1-3]王|首领[1-3](?!\d)|前哨'
    if options.get('boss'):
        scopes += '|'+re.escape(normalized(options['boss']))
    prefix = re.compile(r'^(?:[【\[]?(?:'+scopes+r')[】\]]?|普通|困难|高难|极难|'
                        r'(?:打法|方案|阵容|配队)(?:\d+|[一二三四五六七八九十]+)|通用|共同|共用|全局)[：:]*', re.I)
    identities = sorted(((normalized(name), name) for name in names), key=lambda row: len(row[0]), reverse=True)
    for statement, method in metadata:
        for line in relevant_statements(statement, options).splitlines():
            if not BUILD_LABEL.search(line):
                continue
            content = normalized(line)
            _, scope_end = leading_boss_scope(content)
            if scope_end:
                content = content[scope_end:].lstrip('】]：:')
            while (match := prefix.match(content)):
                content = content[match.end():]
            name = next((original for label, original in identities if content.startswith(label)), None)
            tail = content[len(normalized(name)):].lstrip('：:,，') if name else ''
            fields = []
            while tail and (match := BUILD_VALUE.match(tail)):
                values = labeled_fields(match[0])
                if not values or any(type(value) is int and (
                        not 0 <= value <= 5 if key == 'unique2_stars' else value <= 0)
                        for key, value in values.items()):
                    break
                fields.extend(values.items())
                tail = tail[match.end():].lstrip('：:,，;；')
            tiers = {d for d in ('普通', '困难', '高难', '极难') if d in line}
            difficulty = next(iter(tiers)) if len(tiers) == 1 and not SHARED_REQUIREMENTS.search(line) else None
            rows.append(dict(name=name if fields and not tail else None, fields=fields,
                             text=line, method=method, plan=plan_number(dict(part=line)), difficulty=difficulty))
    return rows


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


def target_scope(options):
    wanted = dict(kind=options['kind'], difficulty=options['difficulty'])
    if wanted['kind'] == 'boss':
        wanted['boss'] = options['boss']
    return wanted


def plan_number(page):
    title = page.get('part', page.get('title', ''))
    if SHARED_REQUIREMENTS.search(title):
        return None
    numbers = list(re.finditer(r'(?:打法|方案|阵容|配队)\s*(\d+|[一二三四五六七八九十]+)', title))
    if len(numbers) != 1 or re.match(r'\s*[/、,，&和及与\-－~～至到]\s*(?:\d|[一二三四五六七八九十])', title[numbers[0].end():]):
        return None
    value = numbers[0][1]
    return int(value) if value.isdecimal() else dict(zip('一二三四五六七八九十', range(1, 11))).get(value)


def constraint_cids(pages, frames):
    """Keep shared/unknown and same-plan conditions; isolate only known other plans."""
    result = {frame['cid'] for frame in frames}
    numbers = {plan_number(page) for page in pages if page['cid'] in result}
    for page in pages:
        number = plan_number(page)
        if number is None or not numbers or None in numbers or number in numbers:
            result.add(page['cid'])
    return result


def applicable_scope(scope, options, *, allow_higher=False, allow_lower=False):
    """Match a source tier; lower boss tiers can only seed free trials."""
    wanted = target_scope(options)
    if scope == wanted:
        return True
    tiers = ('普通', '困难', '高难', '极难') if wanted['kind'] == 'boss' else ('普通', '困难', '高难')
    if (allow_higher and wanted['difficulty'] in tiers[:-1]
            and scope == dict(wanted, difficulty=tiers[-1])):
        return True
    return (allow_lower and wanted['kind'] == 'boss'
            and wanted['difficulty'] in tiers
            and any(scope == dict(wanted, difficulty=tier)
                    for tier in tiers[:tiers.index(wanted['difficulty'])]))


def parties_for_target(report, options, *, allow_local_trials):
    result = []
    wanted = target_scope(options)
    for raw in report.get('parties', []):
        difficulty_trial = raw.get('scope') != wanted and applicable_scope(
            raw.get('scope'), options, allow_higher=allow_local_trials,
            allow_lower=allow_local_trials)
        members = raw.get('members', [])
        names = [m.get('name') for m in members]
        flags = [raw.get('auto', {})]+[m.get('instant', {}) for m in members]
        actions = raw.get('manual_actions') or []
        # A guide's borrowing confirmation is an observation of the source
        # account, not a requirement to borrow. An owned-character trial must
        # still inspect all five builds and pass the current free simulation.
        owned_trial = (allow_local_trials and wanted['kind'] == 'boss' and bool(actions)
            and all(a.get('text') == '要借用这个角色吗？'
                    and a.get('evidence', {}).get('method') == 'video_ocr' for a in actions))
        if ((raw.get('scope') != wanted and not difficulty_trial) or not raw.get('scope_verified')
                or raw.get('region') != 'cn' or raw.get('target_region') != 'cn'
                or raw.get('global_requirements') or actions and not owned_trial
                or len(names) != 5 or any(not isinstance(n, str) or not n or n.startswith('unit:') for n in names)
                or len(set(map(normalized, names))) != 5
                or any(type(f.get('value')) is not bool or not f.get('evidence') or f.get('conflicts') for f in flags)
                or any(m.get(k, {}).get('conflicts') for m in members
                       for k in ('level', 'rank', 'stars', 'skill_level', 'unique', 'unique2', 'unique_level', 'unique2_stars'))):
            continue
        missing = missing_fields(raw)
        live_trial = any(e.get('method') == 'combat_matches_live_target' for e in raw.get('scope_evidence', []))
        if live_trial and not allow_local_trials:
            continue
        if not missing and not difficulty_trial and not live_trial and not owned_trial:
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
        if difficulty_trial:
            candidate.assumptions.append('同一目标'+raw['scope']['difficulty']+'来源用于'+wanted['difficulty']+
                '账号试打，保留来源难度'+('，首领先免费模拟再核验实战' if wanted['kind'] == 'boss' else ''))
        if live_trial:
            candidate.assumptions.append('来源战斗与实时目标的首领、等级和生命上限一致；先免费模拟核验')
        if owned_trial:
            candidate.assumptions.append('来源画面使用过借角；仅核验账号自有五人，免费模拟通过后才实战')
        # A different difficulty has different HP and combat conditions. Its
        # source damage cannot permit spending even when the team is intact.
        candidate.damage_reference = ({} if difficulty_trial else
                                      dict(raw.get('damage_reference', {})))
        result.append(candidate)
    return result
