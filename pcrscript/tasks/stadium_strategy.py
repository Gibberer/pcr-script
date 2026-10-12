"""Current-period, exact-round source rules for the battle stadium."""
from datetime import datetime
import re

from .recollection_strategy import parties_for_floor, RecollectionFormation
from .strategy_inputs import declared_region, source_statements
from ..constants import SERVER_TIMEZONE


def queries(options):
    start = datetime.fromtimestamp(options['period_start'], SERVER_TIMEZONE)
    return [f'公主连结 国服 {start.year}年{start.month}月 斗技场 回合{options["stage"]}',
            f'公主连结 {start.year}年{start.month}月 斗技场 全攻略',
            f'公主连结 {str(start.year)[2:]}年{start.month}月 斗技场',
            f'公主连结 {start.month}月 斗技场']


def source_rejection(source, options):
    text = '\n'.join(t for t, _ in source_statements(source))
    if not re.search('斗技场', text):
        return '来源未确认斗技场玩法'
    if declared_region(text) not in ('cn', 'unknown'):
        return '来源服区不符或冲突'
    published = source.get('published_at')
    if type(published) not in (int, float) or not options['period_start']-7*86400 <= published < options['period_end']:
        return '来源不属于本期活动'
    start = datetime.fromtimestamp(options['period_start'], SERVER_TIMEZONE)
    dates = re.findall(r'(20\d{2}|\d{2})[年./-](\d{1,2})(?:月|[./-]|\b)', text)
    if any((int(y) if len(y) == 4 else 2000+int(y), int(m)) != (start.year, start.month) for y, m in dates):
        return '来源标注年月不符'
    if any(int(m) != start.month for m in re.findall(r'(?<!\d)(\d{1,2})月', text)):
        return '来源标注月份不符'
    # Discovery metadata precedes author-comment acquisition. The shared
    # acquisition path requires complete comments before parsing any party.
    if source.get('comment_complete') is False or source.get('comment_pending'):
        return '作者补充尚未完整读取'
    if any(row.get('images') for row in source.get('author_comments', [])):
        return '作者补充含尚未解析的图片条件'
    return None


def round_scope(text, *, part_title=False):
    # A compilation range or an ordinal team label is not a round identity.
    if re.search(r'\d\s*(?:[-~～—至到]|、|及)\s*\d', text):
        return {}
    values = {int(n) for groups in re.findall(
        r'(?:回合|ROUND)\s*(\d{1,2})(?!\d)|第\s*(\d{1,2})\s*(?:层|回合)(?!\d)', text, re.I)
        for n in groups if n}
    if not values:
        match = re.fullmatch(r'\s*(\d{1,2})(?:层|回合)\s*', text)
        if match:
            values = {int(match[1])}
    if not values and part_title:
        match = re.fullmatch(r'\s*R\s*(\d{1,2})[ab]?\s*',text,re.I)
        if match:
            values = {int(match[1])}
    return dict(round=next(iter(values))) if len(values) == 1 and 1 <= next(iter(values)) <= 99 else {}


def round_collection_title(text, *, number=None):
    """An exact R-series with an endpoint beyond six cannot be gear slots."""
    match = re.fullmatch(r'\s*R\s*(\d{1,2})\s*[-~～—至到]\s*(\d{1,2})\s*', text, re.I)
    return bool(match and 1 <= int(match[1]) <= int(match[2]) <= 99 and int(match[2]) > 6
                and (number is None or int(match[1]) <= int(number) <= int(match[2])))


def collection_candidate(text, options):
    """A period-matched compilation is a candidate, never round proof."""
    scope = round_scope(text)
    return '斗技场' in text and (not scope or scope == dict(round=int(options['stage'])))


def source_options(options, event, number):
    result = dict(options.get('sources', {}))
    result.update(task_type='stadium', region='cn', area='斗技场', aliases=[], category_terms=[],
                  stage=str(number), period_start=event.startTimestamp,
                  period_end=event.extras['battle_end'], event_id=event.extras['schedule_id'],
                  source_urls=options['source_urls'], search=options['discover_sources'],
                  skip_manual_media=True)
    result.setdefault('max_pages_per_video', 24)
    result.setdefault('max_frames_per_page', 600)
    result.setdefault('max_video_seconds', 1200)
    result.setdefault('parse_timeout', 1800)
    return result


def parties_for_round(report, number, *, allow_local_trials=False):
    # Reuse the same unknown-preserving build/identity contract as first clears.
    def confirmed_result(party, outcome):
        proofs = { (e['cid'], e['seconds']) for row in party.get('source_results', [])
            if row.get('outcome') == outcome and isinstance(e := row.get('evidence'), dict)
            and e.get('method') == 'stadium_result_'+outcome
            and type(e.get('cid')) is int and type(e.get('seconds')) in (int,float)
            and isinstance(e.get('image'), str) and e['image']
            and type(e.get('confidence')) in (int,float) and e['confidence'] >= .95 }
        return len(proofs) >= 2
    candidates = [p for p in report.get('parties', [])
                  if confirmed_result(p, 'win') or not confirmed_result(p, 'lose')]
    candidates.sort(key=lambda p: not confirmed_result(p, 'win'))
    adapted = dict(report, parties=[dict(p, scope=dict(area='斗技场', floor=number))
                    for p in candidates if p.get('scope') == dict(round=number)
                    and p.get('task_type') == 'stadium'])
    return parties_for_floor(adapted, '斗技场', number, allow_local_trials=allow_local_trials)


class StadiumFormation(RecollectionFormation):
    """Stadium uses five formation slots and requires known live equipment."""
    all_filter_area = (30, 135, 115, 178)
    search_field_area = (300, 180, 640, 235)
    search_reset_area = (640, 175, 755, 240)
    search_reset = (691, 205)
    search_field = (480, 206)
    search_reveal = ((580, 210), (580, 355))
    search_top = 247
    # The opponent strip leaves less than two full card rows visible. Keep
    # overlap so a 140px drag cannot skip an entire unseen row.
    # The right gutter is the scrollbar, which can reveal search instead of
    # advancing the roster. Swipe the verified gap between columns 7 and 8.
    roster_scroll = ((797, 340), (797, 250))
