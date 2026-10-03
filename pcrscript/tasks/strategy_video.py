"""Formal video-to-strategy acquisition. No Agent files, prompts or labels required."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
import time

import cv2 as cv
import numpy as np
import requests

from ..extras.bilibili_api import BilibiliApi
from ..extras.guide_media import fetch_video
from ..game_ui.avatar_assets import ensure_avatar_index, atomic_json, read_json
from ..game_ui.guide_vision import GuideText, combat_team, formation_team, wide_special_equipment_team, combat_set, combat_auto, battle_rectangles, match_portrait, read_text, requirement_cells, labeled_fields, formation_fields
from .strategy_document import Evidence, Fact, empty_member, finalize, export_document
from .strategy_sources import BORROW_PART, MANUAL_PART, UNVERIFIED_SETTING, discover_sources
from .strategy_inputs import preferred_sources

PARSER_VERSION = 69
FRAME_OCR_VERSION = 1
COMBAT_AUDIT_SECONDS = 20
RECOLLECTION_UNSUPPORTED = re.compile(
    r'特别装备|特別裝備|特装|粉装|属性等级|属性技能|公主骑士|大师点|大師點|\bMP\d|突破|TP\s*\+\s*2|'
    r'(?:Rank|R)\s*\d+\s*[-－]\s*[0-6]|满装|穿\s*\d+\s*件', re.I)
ELEMENTS = {'火': 'fire', '水': 'water', '风': 'wind', '光': 'light', '暗': 'dark',
            '红焰': 'fire', '苍波': 'water', '翠岚': 'wind', '珀天': 'light', '紫冥': 'dark'}


def recollection_client_region(texts):
    """Fixed game controls, rather than creator captions, identify the client."""
    labels = [(t.text, t.rectangle[0]+t.rectangle[2]/2, t.rectangle[1]+t.rectangle[3]/2)
              for t in texts if t.score >= .95]
    for region, title, start, difficulty, first in (
            ('cn', '队伍编组', '战斗开始', '难度变更', '初次通关'),
            ('tw', '隊伍編組', '戰鬥開始', '難度變更', '初次通關')):
        formation = (any(text == title and 300 <= x <= 950 and y < 100 for text, x, y in labels)
                     and any(text == start and x > 850 and y > 530 for text, x, y in labels))
        detail = (any(text == difficulty and x > 900 and 60 < y < 180 for text, x, y in labels)
                  and any(text == first and 100 < x < 600 and 380 < y < 640 for text, x, y in labels))
        if formation or detail:
            return region
    return 'unknown'


class RecollectionScopeContext:
    """Link a visible detail to its fight, requiring matching boss HP and time."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.scope, self.maximum, self.proof = {}, None, None
        self.detail_at, self.timer = float('-inf'), None

    def resolve(self, scope, verified, texts, seconds, combat_scene, proof):
        labels = [t.text.replace(' ', '') for t in texts if t.score >= .94]
        maxima = {int(m[2]) for text in labels
                  if (m := re.fullmatch(r'(\d{7,11})/(\d{7,11})', text))
                  and 0 <= int(m[1]) <= int(m[2])}
        maximum = next(iter(maxima)) if len(maxima) == 1 else None
        timers = {int(m[1])*60+int(m[2]) for text in labels
                  if (m := re.fullmatch(r'(\d{1,2}):(\d{2})', text)) and int(m[2]) < 60}
        timer = next(iter(timers)) if len(timers) == 1 else None
        if scope:
            self.reset()
            if verified and not combat_scene and maximum and '难度变更' in labels:
                self.scope, self.maximum, self.proof = dict(scope), maximum, dict(proof)
                self.detail_at = seconds
            return scope, verified, None
        if any(re.search(r'WIN|战斗胜利|战斗失败|战斗结果|伤害报告', label, re.I) for label in labels):
            self.reset()
            return {}, False, None
        if combat_scene:
            if not maximum or timer is None:
                return {}, False, None
            if (not self.scope or maximum != self.maximum
                    or self.timer is None and seconds-self.detail_at > 15
                    or self.timer is not None and timer > self.timer):
                self.reset()
                return {}, False, None
            self.timer = timer
            evidence = dict(self.proof, method='detail_to_combat',
                            text=f'{self.scope}: boss HP {maximum}; continuous countdown')
            return dict(self.scope), True, evidence
        formation = ('队伍编组' in labels
                     and ('战斗开始' in labels or {'当前的成员', '取消'} <= set(labels)))
        if (formation and self.scope
                and self.timer is None and seconds-self.detail_at <= 15):
            return dict(self.scope), True, dict(self.proof, method='detail_to_formation')
        special_equipment = {'特别装备设定', '可变更队伍角色的特别装备。',
                             '取消', '装备确定'} <= set(labels)
        preparation = (('角色详情' in labels and '确认' in labels)
                       or ('★变更确认' in labels and '取消' in labels and '变更' in labels)
                       or special_equipment
                       or any(t.score >= .9 and t.text.startswith('加载中')
                              and t.rectangle[0] > 850 and t.rectangle[1] > 550 for t in texts))
        if preparation and self.scope and self.timer is None and seconds-self.detail_at <= 15:
            return {}, False, None
        if '正在进行数据连接' not in labels:
            self.reset()
        return {}, False, None


def texts_in_view(texts, raw_width: int, crop_left: int, crop_width: int):
    """Project OCR on the saved 1280x720 frame into the 960x540 combat view."""
    left = crop_left * 1280 / raw_width
    xscale = 960 * raw_width / (1280 * crop_width)
    result = []
    for item in texts:
        x, y, width, height = item.rectangle
        rectangle = (round((x-left)*xscale), round(y*.75),
                     round(width*xscale), round(height*.75))
        if 0 <= rectangle[0]+rectangle[2]/2 <= 960:
            result.append(type(item)(item.text, item.score, rectangle))
    return result


def sample_seconds(duration: float, maximum: int, *, wide: bool = False) -> list[float]:
    """Give opening formations denser coverage while sampling the full video."""
    early = [s for s in ([.5, 1.5, 2.0, 3.5] if wide else [.5, 1.5]) if s < duration]
    regular_count = max(0, maximum-len(early))
    if duration > 90 and regular_count >= 20:
        front = min(60, duration*.4)
        opening = regular_count//2
        regular = list(np.linspace(3, front, opening, endpoint=False))
        regular += list(np.linspace(front, duration, regular_count-opening, endpoint=False))
        return sorted(set(early+regular))
    step = max(1, (duration-3)/max(1, regular_count))
    regular = list(np.arange(3, duration, step))[:regular_count]
    return sorted(set(early+regular))


def frame_texts(frame: np.ndarray, image_path: Path, ocr) -> list[GuideText]:
    """Reuse OCR only for an identical decoded frame and OCR rule version."""
    digest = sha256(frame.tobytes()).hexdigest()
    text_path = image_path.with_suffix('.json')
    cached = read_json(text_path)
    if (image_path.is_file() and cached.get('frame_sha256') == digest
            and cached.get('ocr_version') == FRAME_OCR_VERSION
            and isinstance(cached.get('texts'), list)):
        try:
            if any(not isinstance(row, dict) or len(row['rectangle']) != 4
                   for row in cached['texts']):
                raise ValueError('OCR cache row shape changed')
            return [GuideText(str(row['text']), float(row['score']), tuple(row['rectangle']))
                    for row in cached['texts']]
        except (KeyError, TypeError, ValueError):
            pass
    texts = read_text(frame, ocr)
    cv.imencode('.jpg', frame, [cv.IMWRITE_JPEG_QUALITY, 95])[1].tofile(image_path)
    atomic_json(text_path, dict(frame_sha256=digest, ocr_version=FRAME_OCR_VERSION,
                                texts=[asdict(t) for t in texts]))
    return texts


def combat_button_texts(frame: np.ndarray, small: np.ndarray, boxes, ocr,
                        raw_width: int, crop_left: int, crop_width: int):
    """Recognize only the two-line SET badges and the AUTO button in combat."""
    def recognize(rectangle):
        x, y, w, h = rectangle
        patch = frame[max(0,y):min(720,y+h), max(0,x):min(1280,x+w)]
        if patch.size == 0:
            return '', 0.0
        result = ocr(patch, use_det=False, use_cls=False, use_rec=True)
        if not result.txts or not result.scores:
            return '', 0.0
        return re.sub(r'\s+', '', result.txts[0]), float(result.scores[0])

    def full_rect(x0, y0, x1, y1):
        project_x = lambda x: round((crop_left+x*crop_width/960)*1280/raw_width)
        x0, x1 = project_x(x0), project_x(x1)
        y0, y1 = round(y0*4/3), round(y1*4/3)
        return x0, y0, x1-x0, y1-y0

    set_labels = []
    for x, y, w, h in boxes:
        # An inactive grey badge cannot establish SET=off. Skip its OCR.
        badge = small[max(0,round(y-.16*h)):round(y+.24*h),
                      round(x+.76*w):min(960,round(x+1.32*w))]
        if not badge.size:
            continue
        hsv = cv.cvtColor(badge, cv.COLOR_BGR2HSV)
        cyan = ((hsv[:,:,0] >= 75) & (hsv[:,:,0] <= 115)
                & (hsv[:,:,1] > 100) & (hsv[:,:,2] > 140))
        if float(np.mean(cyan)) < .20:
            continue
        x0, x1 = x+.8*w, x+1.28*w
        top, top_score = recognize(full_rect(x0, y-.13*h, x1, y+.06*h))
        if top != '立即' or top_score < .9:
            continue
        bottom, bottom_score = recognize(full_rect(x0, y+.04*h, x1, y+.22*h))
        if bottom == '发动' and bottom_score >= .95:
            set_labels.append(GuideText('SET', min(top_score, bottom_score),
                              (round(x0), round(y-.13*h), round(x1-x0), round(.35*h))))

    auto_labels = []
    # The uncropped right edge also works for the supported wide layout.
    for x0 in (1110, 1200):
        for y0, y1 in ((505, 550), (530, 575)):
            rectangle = (x0, y0, 65, y1-y0)
            label, score = recognize(rectangle)
            if label.upper() in ('自动', 'AUTO') and score >= .95:
                auto_labels.append(GuideText(label, score, rectangle))
                break
        if auto_labels:
            break
    return set_labels, auto_labels


def combat_caption_signature(frame: np.ndarray) -> frozenset[tuple[int, int]]:
    """Spot changed colored guide captions without recognizing battle scenery."""
    region = frame[round(frame.shape[0]*.14):round(frame.shape[0]*.56),
                   round(frame.shape[1]*.06):round(frame.shape[1]*.37)]
    hsv = cv.cvtColor(region, cv.COLOR_BGR2HSV)
    mask = (((hsv[:,:,0] >= 10) & (hsv[:,:,0] <= 40)
             & (hsv[:,:,1] >= 90) & (hsv[:,:,2] >= 180))*255).astype(np.uint8)
    _, _, stats, _ = cv.connectedComponentsWithStats(mask)
    letters = [(x, y, w, h) for x, y, w, h, area in stats[1:]
               if 80 <= area <= 3000 and 18 <= h <= 100 and 12 <= w <= 200]
    if not any(sum(abs(other[1]-y) <= 25 and abs(other[3]-h) <= 25
                   for other in letters) >= 5 for _, y, _, h in letters):
        return frozenset()
    return frozenset(((x+w//2)//30, (y+h//2)//30) for x, y, w, h in letters)


def combat_hud_visible(image: np.ndarray) -> bool:
    """Keep a confirmed battle scene through brief card contour occlusion."""
    region = image[round(image.shape[0]*.67):round(image.shape[0]*.91),
                   round(image.shape[1]*.18):round(image.shape[1]*.82)]
    hsv = cv.cvtColor(region, cv.COLOR_BGR2HSV)
    cyan = ((hsv[:,:,0] >= 75) & (hsv[:,:,0] <= 105)
            & (hsv[:,:,1] > 100) & (hsv[:,:,2] > 150))
    return int(np.count_nonzero(cyan)) >= 6000


def declared_abyss_element(title: str) -> str | None:
    matches = {ELEMENTS[m] for m in re.findall(r'(红焰|苍波|翠岚|珀天|紫冥|火|水|风|光|暗)(?:属性)?(?:深域|\s*\d+\s*[-－])', title)}
    return next(iter(matches)) if len(matches) == 1 else None


def matches_abyss_request(party: dict, element: str, stage: str) -> bool:
    scope = party['scope']
    if scope.get('element') != element:
        return False
    if scope.get('stage'):
        return scope['stage'] == stage
    chapters = scope.get('chapters')
    if chapters:
        chapter = int(stage.split('-')[0])
        return chapters[0] <= chapter <= chapters[1]
    # Retain an unscoped table for review, never as an executable source.
    return not party.get('scope_verified')


def task_source_options(kind: str, options: dict, *, stage=None,
                        area: str | None = None, difficulty: str | None = None,
                        mode: int | None = None) -> dict:
    from ..game_ui.abyss import AREAS
    result = dict(options.get('sources', {}))
    result.update(task_type=kind, region='cn')
    result['source_urls'] = options.get('source_urls') or result.get('source_urls', [])
    if kind == 'abyss':
        effort = options.get('search_effort', 'normal')
        if effort not in ('normal', 'high'):
            raise ValueError('Abyss.search_effort必须为normal或high')
        result['search_effort'] = effort
        if effort == 'high':
            # Floors also work when a saved GUI configuration still contains
            # the normal preset's explicit source limits.
            for key, minimum in [('max_videos', 12), ('max_pages_per_video', 8),
                                 ('max_frames_per_page', 96), ('max_video_seconds', 600),
                                 ('max_download_seconds', 420), ('parse_timeout', 3600)]:
                configured = result.get(key, minimum)
                if type(configured) is not int or configured < 1:
                    raise ValueError(f'sources.{key}必须为正整数')
                result[key] = max(configured, minimum)
        result['skip_manual_media'] = not options.get('prepare_only', False)
        result['skip_long_media'] = not options.get('prepare_only', False)
        if stage is not None:
            result.update(element=stage.element, stage=stage.key)
        element = result.get('element', options.get('elements', ['fire'])[0])
        if element not in AREAS:
            raise ValueError('来源目标属性无效')
        result.update(element=element, area=AREAS[element][0], category_terms=['深域'],
                      aliases=['深域 '+AREAS[element][1][0], AREAS[element][1][0]])
        if not result.get('stage'):
            raise ValueError('仅解析攻略时请在sources.stage指定目标关卡，如4-1')
    elif kind == 'dungeon':
        result['area'] = options.get('area', '四彩的灵峰')
        result.setdefault('aliases', ['极难7', 'EX7'] if result['area'] == '四彩的灵峰' else [])
        result.setdefault('max_pages_per_video', 12)
    elif kind in ('event', 'revival'):
        if not area or difficulty not in ('special', 'special_plus', 'very_hard') or mode not in (1, 2, 3):
            raise ValueError('活动攻略必须明确活动名称、首领难度与模式')
        result.pop('stage', None)
        result.pop('element', None)
        result.update(area=area, difficulty=difficulty, mode=mode,
                      category_terms=[], aliases=[])
    elif kind == 'recollection':
        from ..game_ui.recollection import AREAS, ALIASES
        if area not in AREAS.values() or type(stage) is not int or not 1 <= stage <= 99:
            raise ValueError('追忆战攻略必须明确领域与层数')
        key = next(key for key, name in AREAS.items() if name == area)
        result.update(area=area, stage=str(stage), category_terms=['追忆', '追憶'],
                      aliases=list(ALIASES[key]), search=options.get('discover_sources', True))
        result.pop('element', None)
        result.setdefault('max_video_seconds', 600)
        result.setdefault('max_frames_per_page', 96)
        result.setdefault('max_pages_per_video', 8)
    else:
        raise ValueError('未知攻略任务类型')
    return result


def event_page_difficulty(title: str) -> str | None:
    if re.search(r'特别(?:战斗)?\s*[＋+]|SP\s*[＋+]', title, re.I):
        return 'special_plus'
    if re.search(r'特别(?:战斗)?(?!装备)|(?<![a-z0-9])SP(?![a-z0-9＋+])', title, re.I):
        return 'special'
    if re.search(r'高难|VERY\s*HARD|(?<![a-z0-9])VH(?![a-z0-9])', title, re.I):
        return 'very_hard'
    if re.search(r'剧本模式|SCENARIO|^Sce$', title, re.I):
        return 'scenario'
    return None


def page_scope(page: dict, kind: str) -> dict:
    title = page.get('part', page.get('title', ''))
    if kind == 'recollection':
        from ..game_ui.recollection import text_scope
        return text_scope(title)
    if kind == 'abyss':
        match = re.search(r'(红焰|苍波|翠岚|珀天|紫冥|火|水|风|光|暗)(?:属性|深域)?[】\]）)]?\s*(\d+)\s*[-－]\s*(\d+)(?!\d|图)', title)
        if match:
            return dict(element=ELEMENTS[match[1]], stage=f'{int(match[2])}-{int(match[3])}',
                        chapters=[int(match[2]), int(match[2])])
    if kind == 'dungeon':
        floor = re.search(r'(?:第|现在的阶数)?\s*([1-5])(?:/5)?\s*(?:层|阶层)', title)
        phase = re.search(r'四色妖狐[·・]?([春夏秋冬][^\s\n]{0,2})', title)
        if floor:
            value = int(floor[1])
            if value < 5 or phase:
                return dict(floor=value, phase=phase[0] if phase else '')
        if phase:
            return dict(floor=5, phase=phase[0])
    if kind in ('event', 'revival'):
        difficulty = event_page_difficulty(title)
        phase = re.search(r'(?:模式|MODE|阶段)\s*([123])', title, re.I)
        if difficulty and phase:
            return dict(difficulty=difficulty, mode=int(phase[1]))
    return {}


def exact_full_set_claim(source: dict, scope: dict, kind: str) -> bool:
    """Use an explicit single-stage video title as SET evidence."""
    if kind != 'abyss' or len(source.get('pages', [])) != 1:
        return False
    title = source.get('title', '')
    declared = page_scope({'part': title}, kind)
    return (bool(re.search(r'全\s*SET', title, re.I))
            and not MANUAL_PART.search(title) and not BORROW_PART.search(title)
            and declared.get('element') == scope.get('element')
            and declared.get('stage') == scope.get('stage'))


def choose_pages(source: dict, options: dict) -> list[dict]:
    """Requirements plus the requested stage, not just the first three parts."""
    kind = options['task_type']
    stage, element = options.get('stage'), options.get('element')
    pages = source.get('pages', [])
    requirements = [p for p in pages if re.search(r'练度|培养|角色需求|配置要求', p.get('part', p.get('title', '')))]
    if kind == 'abyss' and stage:
        source_element = declared_abyss_element(source.get('title', ''))
        if source_element and element and source_element != element:
            return []
        targets = [p for p in pages if (scope := page_scope(p, kind)).get('stage') == stage
                   and (not element or scope.get('element') == element)]
        # In a title such as "水深域1-7图", parts "1-5"/"6-7" divide
        # chapters. They are not exact stages 1-5 and 6-7. Only parse the
        # range containing the requested chapter; visible frames still have
        # to prove the exact stage before any roster is applicable.
        chapter_title = re.search(r'(\d+)\s*[-－]\s*(\d+)图',source.get('title',''))
        combat_pages = [p for p in pages if p not in requirements]
        chapter_parts = [(p,re.fullmatch(r'(\d+)\s*[-－]\s*(\d+)(?:图)?',
                                         p.get('part',p.get('title','')).strip())) for p in combat_pages]
        range_collection = bool(chapter_title and chapter_parts and
                                all(match and int(chapter_title[1]) <= int(match[1]) <= int(match[2]) <= int(chapter_title[2])
                                    for _,match in chapter_parts))
        if range_collection:
            chapter=int(stage.split('-')[0])
            targets=[p for p,match in chapter_parts if int(match[1])<=chapter<=int(match[2])]
            if not targets:
                return []
        if not targets and not range_collection and element and source_element == element:
            # A single-element collection often calls each part only "5-1".
            # The source title supplies the element and the part supplies the
            # stage; retain both original labels as metadata evidence.
            target_label = {'fire':'火','water':'水','wind':'风','light':'光','dark':'暗'}[element]
            targets = [dict(p, original_part=p.get('part', p.get('title', '')), part=target_label+stage)
                       for p in pages if re.fullmatch(re.escape(stage)+r'(?:[（(][^）)]*[）)]?)?',
                                                        p.get('part', p.get('title', '')).strip())]
        if not targets and not range_collection and len(pages) == 1:
            # Single-part uploads often put the stage in the main title.
            scope = page_scope({'part': source['title']}, kind)
            targets = [dict(pages[0], part=source['title'])] if scope.get('stage') == stage and (not element or scope.get('element') == element) else []
        if not targets and not range_collection:
            # A compilation may label only its chapter range. Inspect its
            # frames, but never infer the requested stage from that label.
            targets = [p for p in pages if not page_scope(p, kind)
                       and (not element or declared_abyss_element(p.get('part', p.get('title', ''))) in (None, element))]
    elif kind == 'recollection':
        from ..game_ui.recollection import AREAS, ALIASES
        area = options.get('area')
        from .strategy_sources import recollection_ranges
        names = ALIASES[next(key for key, value in AREAS.items() if value == area)]
        wanted = dict(area=area, floor=int(options['stage']))
        def declared_areas(label):
            # "追忆战·霸" names the mode, not the ordinary memory domain.
            areas = {AREAS[key] for key, aliases in ALIASES.items()
                     if any(name in label for name in aliases if name != '追忆战')}
            if re.search(r'追忆战\s*(?:第)?[1-9]\d?(?!\d)', label):
                areas.add(AREAS['memory'])
            return areas
        source_areas = declared_areas(source.get('title', ''))
        def bare_ranges(label):
            return [(int(a), int(b)) for a, b in re.findall(
                r'(?<!\d)([1-9]\d?)(?:层)?\s*[~～至到\-－]\s*(?:第)?([1-9]\d?)(?:层)?(?!\d)', label)]
        def relevant_requirement(page):
            label = page.get('part', page.get('title', ''))
            scope = page_scope(page, kind)
            if scope:
                return scope == wanted
            labeled_areas = declared_areas(label)
            if labeled_areas and area not in labeled_areas:
                return False
            ranges = recollection_ranges(label, area)
            # Preserve the existing exclusion for a leading floor range.
            # Additional prefixed ranges are reviewed only within a title
            # naming exactly one domain; they never establish battle scope.
            leading = re.match(r'^(?:第)?([1-9]\d?)(?:层)?\s*[~～至到\-－]\s*(?:第)?([1-9]\d?)', label)
            if leading:
                ranges.append((int(leading[1]), int(leading[2])))
            if not labeled_areas and source_areas == {area}:
                ranges.extend(bare_ranges(label))
            return not ranges or any(a <= wanted['floor'] <= b for a, b in ranges)
        requirements = [p for p in requirements if relevant_requirement(p)]
        targets = [p for p in pages if page_scope(p, kind) == wanted]
        if not targets and len(pages) == 1 and page_scope({'part': source.get('title', '')}, kind) == wanted:
            targets = [dict(pages[0], part=source['title'])]
        if (not targets and len(pages) == 1 and any(a <= wanted['floor'] <= b
                for a, b in recollection_ranges(source.get('title', ''), area))):
            # A timestamp-like part name cannot discard a same-domain
            # collection. Its unchanged label still needs exact frame scope.
            targets = [pages[0]]
        # A range/collection is only a candidate: frames must establish an exact floor.
        targets += [p for p in pages if p not in requirements and p not in targets
                    and not page_scope(p, kind)
                    and (any(name in p.get('part', p.get('title', '')) for name in names)
                         or (source_areas == {area}
                             and (re.fullmatch(r'(?:第)?'+str(wanted['floor'])+r'层(?:\s.*)?',
                                               p.get('part', p.get('title', '')))
                                  or any(a <= wanted['floor'] <= b for a, b in
                                         bare_ranges(p.get('part', p.get('title', '')))))))
                    and relevant_requirement(p)
                    and (not (ranges := recollection_ranges(p.get('part', p.get('title', '')), area))
                         or any(a <= wanted['floor'] <= b for a, b in ranges))]
    elif kind == 'subjugation':
        from .subjugation_guides import choose_pages as subjugation_pages, requirement_pages
        requirements = requirement_pages(source, options)
        required_cids = {p['cid'] for p in requirements}
        targets = [p for p in subjugation_pages(source, options) if p['cid'] in required_cids]
    elif kind in ('event', 'revival'):
        wanted = {'difficulty': options.get('difficulty'), 'mode': options.get('mode')}
        targets = [p for p in pages if (scope := page_scope(p, kind)) == wanted]
        if not targets and len(pages) == 1 and page_scope({'part': source.get('title', '')}, kind) == wanted:
            targets = [dict(pages[0], part=source['title'])]
        # An unlabeled page can still prove its scope from visible battle text.
        chosen_cids = {p.get('cid') for p in targets}
        targets += [p for p in pages if p not in requirements and p.get('cid') not in chosen_cids
                    and not page_scope(p, kind)
                    and event_page_difficulty(p.get('part', p.get('title', ''))) in (None, wanted['difficulty'])]
    else:
        targets = [p for p in pages if p not in requirements]
    limit = options.get('max_pages_per_video', 4)
    if type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError('max_pages_per_video必须为1到30')
    if kind == 'subjugation':
        target_cids = {p['cid'] for p in targets}
        # Parse all potentially relevant parts, including blank/unknown titles.
        # A budget cannot turn an unread condition into permission to fight.
        ordered = [p for p in requirements if p['cid'] not in target_cids] + targets
        selected = list({p['cid']: p for p in ordered}.values())
        if len(selected) > limit:
            raise ValueError(f'攻略说明页与候选关卡无法在 max_pages_per_video={limit} 上限内完整解析，拒绝该来源')
        return selected
    # Reserve a combat slot; a stage part mentioning training uses one CID.
    selected = list({p['cid']: p for p in requirements[:max(0, limit-1)]}.values())
    for page in targets:
        duplicate = next((i for i, saved in enumerate(selected) if saved['cid'] == page['cid']), None)
        if duplicate is not None:
            selected[duplicate] = page
        elif len(selected) < limit:
            selected.append(page)
    return selected


def declared_region(text: str) -> str:
    # Creator overlays can recruit for several servers. A guild advert does
    # not declare the server in which the demonstrated battle was recorded.
    text = re.sub(r'(?:国服|國服|日服|台服|臺服)\s*(?:公会|公會|行会|行會)', '', text)
    values = {code for code, pattern in [('cn', '国服|國服'), ('jp', '日服'), ('tw', '台服|臺服')]
              if re.search(pattern, text)}
    return next(iter(values)) if len(values) == 1 else 'conflict' if values else 'unknown'


def observed_scope(texts, page: dict, kind: str, *, battle_scope: dict | None = None) -> tuple[dict, bool]:
    metadata = page_scope(page, kind)
    if kind == 'recollection':
        scopes = [page_scope({'part': t.text}, kind) for t in texts if t.score >= .94]
        scopes = [s for s in scopes if s]
        if ((metadata and any(s != metadata for s in scopes))
                or scopes and any(s != scopes[0] for s in scopes)):
            return {'conflict': True}, False
        return (scopes[0], True) if scopes else (metadata, bool(metadata))
    if kind == 'abyss':
        scopes = [page_scope({'part': t.text}, kind) for t in texts if t.score >= .94]
        scopes = [s for s in scopes if s]
        if metadata and any(s != metadata for s in scopes):
            return metadata, False
        if scopes and any(s != scopes[0] for s in scopes):
            return {'conflict': True}, False
        return (scopes[0], True) if scopes and all(s == scopes[0] for s in scopes) else (metadata, bool(metadata))
    if kind == 'dungeon':
        text = '\n'.join(t.text for t in texts if t.score >= .94)
        floor = re.search(r'(?:现在的阶数|第?)\s*([1-5])(?:/5)?[阶层]', text)
        phase = re.search(r'四色妖狐[·・]?([春夏秋冬][^\s\n]{0,2})', text)
        if floor:
            if int(floor[1]) == 5 and not phase and metadata.get('floor') == 5:
                return metadata, True
            scope = dict(floor=int(floor[1]), phase=phase[0] if phase else '')
            if metadata and scope != metadata:
                return {'conflict': True}, False
            return scope, int(floor[1]) < 5 or bool(phase)
        if phase:
            scope = dict(floor=5, phase=phase[0])
            return ({'conflict': True}, False) if metadata and scope != metadata else (scope, True)
        if metadata:
            return metadata, True
    if kind in ('event', 'revival'):
        scopes = [page_scope({'part': t.text}, kind) for t in texts if t.score >= .94]
        scopes.append(page_scope({'part': '\n'.join(t.text for t in texts if t.score >= .94)}, kind))
        # SP+ result pages explicitly pair the current phase with remaining
        # run attempts. Regular SP shows a challenge ordinal instead. This
        # establishes the scope of a following retry in the same video part.
        remaining = [t for t in texts if t.score >= .94 and t.center[1] < 130
                     and re.search(r'剩余挑战次数\s*\d+\s*/\s*\d+', t.text)]
        result_phases = {int(m[1]) for t in texts if t.score >= .94 and t.center[1] < 130
                         for m in re.finditer(r'阶段\s*([123])', t.text)}
        if remaining and len(result_phases) == 1 and any(
                t.score >= .94 and '再次挑战' in t.text for t in texts):
            if event_page_difficulty(page.get('part', page.get('title', ''))) not in (None, 'special_plus'):
                return {'conflict': True}, False
            scopes.append(dict(difficulty='special_plus', mode=next(iter(result_phases))))
        difficulty = event_page_difficulty(page.get('part', page.get('title', '')))
        if difficulty in ('special', 'special_plus', 'very_hard'):
            # A HUD phase may advance within one challenge. Its settings
            # still belong to the challenge's starting mode, not a new party.
            phases = {int(m[1]) for t in texts if t.score >= .94
                      and not page_scope({'part': t.text}, kind)
                      for m in re.finditer(r'(?:模式|MODE|阶段)\s*([123])', t.text, re.I)}
            if len(phases) > 1:
                return {'conflict': True}, False
            if phases:
                phase = next(iter(phases))
                start = metadata or battle_scope or {}
                if start.get('difficulty') == difficulty and start.get('mode'):
                    if phase < start['mode']:
                        return {'conflict': True}, False
                    phase = start['mode']
                scopes.append(dict(difficulty=difficulty, mode=phase))
        scopes = [s for s in scopes if s]
        if metadata and any(s != metadata for s in scopes):
            return {'conflict': True}, False
        if scopes and any(s != scopes[0] for s in scopes):
            return {'conflict': True}, False
        return (scopes[0], True) if scopes else (metadata, bool(metadata))
    return {}, False


def requirement_scope(texts) -> list[int] | None:
    values = []
    for t in texts:
        if t.score < .95:
            continue
        match = re.search(r'\(?([1-9]\d?)[-－][Xx](?:首通|\))', t.text)
        if match:
            values.append(int(match[1]))
    return [values[0], values[0]] if values and len(set(values)) == 1 else None


def manual_requirement(text):
    return bool(MANUAL_PART.search(text) or BORROW_PART.search(text) or re.search(
        r'手动|目押|卡[秒帧]|连点|关闭自动|关AUTO|轴[:：]|改星|调星|切星|降星|星级变更|\d[:：]\d{2}.*(?:开|关|点|放)',
        text, re.I))


def text_constraints(texts, proof: Evidence) -> tuple[list[dict], list[dict]]:
    global_requirements, manual = [], []
    for t in texts:
        if t.score < .94:
            continue
        row = dict(text=t.text, evidence=asdict(Evidence(**{**asdict(proof), 'text': t.text,
                                                          'rectangle': list(t.rectangle), 'confidence': t.score})))
        if re.search(r'属性等级|属性技能|公主骑士|\bMP\d|突破', t.text, re.I):
            row['advisory'] = bool(re.search(r'建议|推荐|可选', t.text))
            global_requirements.append(row)
        if manual_requirement(t.text):
            manual.append(row)
    return global_requirements, manual


def event_record_rows(frame, texts, index):
    """Read explicit starting modes and five portraits from battle records."""
    headings = [t for t in texts if t.score >= .95 and '战斗记录' in t.text
                and t.center[1] < 110]
    if len(headings) != 1:
        return []
    difficulty = event_page_difficulty(headings[0].text)
    if difficulty not in ('special', 'special_plus'):
        return []
    rows = []
    for label in texts:
        mode = re.fullmatch(r'MODE([123])', label.text, re.I)
        if not mode or label.score < .95 or not (label.center[0] < 250 and 180 < label.center[1] < 540):
            continue
        if not any(t.score >= .95 and re.fullmatch(r'挑战第\d+次', t.text)
                   and 240 < t.center[0] < 450 and abs(t.center[1]-label.center[1]) < 25 for t in texts):
            continue
        top = round(label.center[1]-10)
        matches = [match_portrait(frame, (602+108*i, top, 96, 96), index, margin=.04) for i in range(5)]
        if all(matches) and len({m['name'] for m in matches}) == 5:
            rows.append(dict(difficulty=difficulty, mode=int(mode[1]), members=matches))
    return rows


def parse_video_source(source: dict, options: dict, index, *, api=None, ocr=None,
                       media_fetcher=fetch_video, check=lambda: None) -> dict:
    """Return candidates plus field evidence, including incomplete/contradictory ones."""
    if options['task_type'] == 'subjugation':
        if source.get('comment_pending') or source.get('comment_complete') is False:
            raise ValueError('作者评论补充未读取完成：'+str(source.get('comment_pending') or '仅取得部分评论'))
        for comment in source.get('author_comments', []):
            if comment.get('images'):
                raise ValueError(f'作者评论{comment.get("reply_id")}含未解析图片，不能确认攻略要求完整')
    from rapidocr import RapidOCR
    from .strategy_tables import universal_row
    api = api or BilibiliApi(timeout=options.get('request_timeout', 20), browser_session=True)
    root = Path(options.get('parsed_dir', 'cache/game/strategies/parsed'))/source['bvid']
    root.mkdir(parents=True, exist_ok=True)
    pages = choose_pages(source, options)
    fingerprint = sha256(json.dumps(dict(version=PARSER_VERSION, source=source, pages=pages,
                         scope={k: options.get(k) for k in ('task_type', 'stage', 'element', 'area', 'difficulty', 'mode', 'region', 'max_frames_per_page', 'max_video_seconds', 'skip_manual_media', 'skip_long_media')},
                         event={k: options.get(k) for k in ('kind', 'boss', 'boss_number', 'event_id', 'period_start', 'period_end')}
                               if options['task_type'] == 'subjugation' else {},
                         index=sha256(index.matrix.tobytes()+json.dumps(index.names, ensure_ascii=False).encode()).hexdigest()), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    cache = root/(fingerprint[:24]+'.json')
    saved = read_json(cache)
    if (saved.get('fingerprint') == fingerprint and not saved.get('errors')
            and (saved.get('parties') or options['task_type'] == 'subjugation')
            and 0 <= time.time()-saved.get('parsed_at', 0) < options.get('max_age_hours', 24)*3600):
        paths = [e.get('image') for p in saved.get('parties', []) for m in p['members']
                 for key in ('stars', 'unique', 'unique2', 'instant') for e in m[key].get('evidence', []) if e.get('image')]
        if all(Path(p).is_file() for p in paths):
            return dict(saved, cache_hit=True)
    # Match the game's OCR worker limits. Default ONNX sessions can otherwise
    # spin a full thread pool for each engine throughout multi-page parsing.
    ocr = ocr or RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": 2,
                                 "EngineConfig.onnxruntime.inter_op_num_threads": 1})
    from ..game_ui.equipment import EquipmentBadges
    badges = EquipmentBadges()
    names = sorted({str(n) for n in index.names if not str(n).startswith('unit:')}, key=len, reverse=True)
    teams = {}
    character_facts = defaultdict(list)
    globals_, manual = [], []
    metadata_build = []
    records = []
    errors, pages_report = [], []
    source_region = declared_region(source.get('title', '')+' '+source.get('description', ''))
    text_source = '\n'.join([source.get('description', '')]+[r.get('text', '') for r in source.get('author_comments', [])])
    if options['task_type'] in ('recollection', 'subjugation'):
        unsupported = source.get('title', '')+'\n'+text_source
        if options['task_type'] == 'subjugation':
            from .subjugation_guides import relevant_statements
            unsupported = relevant_statements(unsupported, options)
        if RECOLLECTION_UNSUPPORTED.search(unsupported):
            globals_.append(dict(text=unsupported[:500], advisory=False, evidence=asdict(Evidence(
                source['url'], method='source_requirements', text=unsupported[:500]))))
    if options['task_type'] == 'subjugation':
        metadata = [(source.get('title', ''), 'source_title'),
                    (source.get('description', ''), 'source_description')]
        metadata.extend((r.get('text', ''), 'author_comment:'+str(r.get('reply_id')))
                        for r in source.get('author_comments', []))
        from .subjugation_guides import metadata_build_requirements
        metadata_build = metadata_build_requirements(metadata, options, names)
        for statement, method in metadata:
            for line in relevant_statements(statement, options).splitlines():
                if manual_requirement(line):
                    manual.append(dict(text=line, evidence=asdict(Evidence(
                        source['url'], method=method, text=line))))
        source_setting = bool(manual)
    else:
        title_setting = UNVERIFIED_SETTING.search(source.get('title') or '')
        source_setting = title_setting or UNVERIFIED_SETTING.search(source.get('description') or '')
        if source_setting:
            setting_text = (source.get('title') if title_setting else source.get('description')) or ''
            manual.append(dict(text=setting_text[:240], evidence=asdict(Evidence(
                source['url'], int(pages[0]['cid']) if pages else 0,
                method='source_title' if title_setting else 'source_description', text=setting_text[:240]))))
    for page in pages:
        check()
        page_name = page.get('part', page.get('title', ''))
        if options['task_type'] in ('recollection', 'subjugation') and RECOLLECTION_UNSUPPORTED.search(page_name):
            globals_.append(dict(text=page_name, advisory=False, evidence=asdict(Evidence(
                source['url'], int(page['cid']), method='part_requirements', text=page_name))))
        requirements_page = bool(re.search(r'练度|培养|角色需求|配置要求', page_name))
        original_part = page.get('original_part', page_name)
        manual_part = manual_requirement(original_part)
        if manual_part:
            manual.append(dict(text=original_part, evidence=asdict(Evidence(
                source['url'], int(page['cid']), method='part_title', text=original_part))))
            if options.get('skip_manual_media'):
                pages_report.append(dict(cid=page['cid'], title=page_name,
                                         skipped='标题要求手动操作、借角或未核实TP+2，自动任务不下载此分P'))
                continue
        if source_setting and options.get('skip_manual_media'):
            pages_report.append(dict(cid=page['cid'], title=page_name,
                                     skipped='来源声明手动、借角或未核实TP+2/大师点条件，自动任务不下载此分P'))
            continue
        page_duration = float(page.get('duration') or 0)
        if (options.get('skip_long_media') and page_duration > 0
                and page_duration > float(options.get('max_video_seconds', 180))):
            pages_report.append(dict(cid=page['cid'], title=page_name,
                                     skipped='分P时长超出自动解析上限，未下载',
                                     duration=page_duration,
                                     max_video_seconds=float(options.get('max_video_seconds', 180))))
            continue
        try:
            video, media = media_fetcher(api, source['bvid'], page,
                                       Path(options.get('media_dir', 'cache/game/strategies/media')),
                                       timeout=options.get('request_timeout', 20),
                                       max_seconds=options.get('max_download_seconds', 180), check=check)
        except (requests.RequestException, RuntimeError, ValueError, OSError) as error:
            errors.append(dict(cid=page['cid'], error=str(error)))
            continue
        capture = cv.VideoCapture(str(video))
        page_record = dict(cid=page['cid'], title=page_name, media=media, frames=0, recognized_teams=0)
        pages_report.append(page_record)
        duration = min(float(page.get('duration') or media['duration']), float(options.get('max_video_seconds', 180)))
        if float(page.get('duration') or media['duration']) > duration:
            page_record['truncated'] = True
        wide = media.get('height', 0) > 0 and 1.9 < media.get('width', 0)/media['height'] <= 2.4
        seconds_list = sample_seconds(duration, options.get('max_frames_per_page', 50), wide=wide)
        if options['task_type'] in ('event', 'revival') and duration > 5 and len(seconds_list) >= 4:
            # Results often appear only in the final seconds. Retain two
            # observations within the existing frame budget for mode evidence.
            seconds_list = sorted(set(seconds_list[:-2]+[duration-1.5, duration-.5]))
        previous = None
        last_scope = ({}, False)
        recollection_scope = RecollectionScopeContext()
        from .subjugation_guides import ScopeContext
        subjugation_scope = ScopeContext()
        combat_seen = 0
        last_combat_audit = float('-inf')
        last_combat_box = float('-inf')
        last_caption = frozenset()
        try:
            for seconds in seconds_list:
                check()
                capture.set(cv.CAP_PROP_POS_MSEC, float(seconds)*1000)
                ok, raw = capture.read()
                if not ok:
                    page_record['unread_frames'] = page_record.get('unread_frames', 0)+1
                    continue
                aspect = raw.shape[1]/raw.shape[0]
                wide_crop = 1.9 < aspect <= 2.4
                if not 1.6 <= aspect <= 1.9 and not wide_crop:
                    page_record['unsupported_aspect'] = True
                    continue
                # OCR retains 720p detail; combat recognition uses the shared 960x540 design space.
                frame = cv.resize(raw, (1280, 720))
                if wide_crop:
                    crop_width = round(raw.shape[0]*16/9)
                    crop_left = (raw.shape[1]-crop_width)//2
                    small = cv.resize(raw[:,crop_left:crop_left+crop_width], (960, 540))
                else:
                    small = cv.resize(raw, (960, 540))
                digest = sha256(cv.resize(frame, (160, 90)).tobytes()).hexdigest()
                # Still sample static pages twice to confirm numeric OCR.
                if previous == (digest, 2):
                    continue
                previous = (digest, previous[1]+1) if previous and previous[0] == digest else (digest, 1)
                image_path = root/f'{page["cid"]}_{seconds:.3f}.jpg'
                # Five verified cyan card borders distinguish combat from
                # formation/table pages even when an avatar is still unknown.
                combat_boxes = battle_rectangles(small, relaxed=wide_crop)
                found = combat_team(small, index, relaxed=wide_crop)
                combat_scene = bool(combat_boxes) or (
                    seconds-last_combat_box <= 8 and combat_hud_visible(small))
                if combat_boxes:
                    if seconds-last_combat_box > 8:
                        combat_seen = 0
                    last_combat_box = seconds
                if combat_scene:
                    combat_seen += 1
                else:
                    combat_seen = 0
                    last_caption = frozenset()
                caption = combat_caption_signature(frame) if combat_scene else frozenset()
                if not caption:
                    last_caption = frozenset()
                caption_changed = bool(caption) and (
                    len(caption & last_caption)/max(1, len(caption | last_caption)) < .5)
                full_ocr = (options['task_type'] == 'subjugation' or not combat_scene or combat_seen <= 2
                            or seconds-last_combat_audit >= COMBAT_AUDIT_SECONDS
                            or caption_changed)
                if full_ocr:
                    texts = frame_texts(frame, image_path, ocr)
                    page_record['full_ocr_frames'] = page_record.get('full_ocr_frames', 0)+1
                    if any(t.score >= .94 and t.text.strip() for t in texts):
                        page_record['readable_text_frames'] = page_record.get('readable_text_frames', 0)+1
                    if combat_scene:
                        last_combat_audit = seconds
                        last_caption = caption
                else:
                    texts = []
                    cv.imencode('.jpg', frame, [cv.IMWRITE_JPEG_QUALITY, 95])[1].tofile(image_path)
                    page_record['combat_fast_frames'] = page_record.get('combat_fast_frames', 0)+1
                page_record['frames'] += 1
                proof = Evidence(source['url'], int(page['cid']), float(seconds), str(image_path), method='video_ocr')
                if options['task_type'] in ('event', 'revival') and not wide_crop:
                    records.extend(dict(row, evidence=asdict(proof)) for row in event_record_rows(frame, texts, index))
                detected_region = declared_region('\n'.join(t.text for t in texts if t.score >= .95))
                if options['task_type'] in ('recollection', 'subjugation') and detected_region == 'unknown':
                    detected_region = recollection_client_region(texts)
                if detected_region != 'unknown':
                    source_region = detected_region if source_region == 'unknown' else source_region if source_region == detected_region else 'conflict'
                global_rows, manual_rows = text_constraints(texts, proof)
                globals_.extend(global_rows)
                manual.extend(manual_rows)
                if options['task_type'] in ('recollection', 'subjugation'):
                    globals_.extend(dict(text=t.text, advisory=False, evidence=asdict(proof)) for t in texts
                                    if t.score >= .94 and RECOLLECTION_UNSUPPORTED.search(t.text)
                                    and t.text not in ('特别装备设定', '可变更队伍角色的特别装备。'))
                if (options['task_type'] != 'subjugation' and not wide_crop
                        and (requirements_page or any('角色需求' in t.text or '练度' in t.text for t in texts))):
                    chapter_scope = requirement_scope(texts)
                    for row in requirement_cells(frame, texts, index):
                        evidence = Evidence(**{**asdict(proof), 'text': row['text'], 'rectangle': row['rectangle'],
                                               'confidence': row['confidence'], 'method': 'avatar_labeled_cell'})
                        character_facts[row['name']].append((row['field'], row['value'], evidence, chapter_scope))
                scope, verified = observed_scope(texts, page, options['task_type'],
                    battle_scope=last_scope[0] if combat_scene and combat_seen > 1 else None)
                scope_evidence = None
                if options['task_type'] == 'subjugation':
                    from .subjugation_guides import visible_scope
                    scope, verified = visible_scope(texts, page, options)
                    scope, verified, scope_evidence = subjugation_scope.resolve(
                        scope, verified, texts, seconds, combat_scene, asdict(proof))
                if options['task_type'] == 'recollection' and not page_scope(page, 'recollection'):
                    scope, verified, scope_evidence = recollection_scope.resolve(
                        scope, verified, texts, seconds, combat_scene, asdict(proof))
                if scope and not verified:
                    # Conflicting visible stage labels must invalidate the frame.
                    last_scope = ({}, False)
                    continue
                if verified:
                    last_scope = scope, verified
                elif options['task_type'] in ('recollection', 'subjugation'):
                    # Unlinked compilation frames cannot inherit a floor.
                    scope, verified = {}, False
                elif options['task_type'] != 'abyss' or page_scope(page, options['task_type']):
                    scope, verified = last_scope
                if options['task_type'] == 'dungeon':
                    area = options.get('area', '')
                    description = source.get('title', '')+' '+source.get('description', '')+' '+page_name
                    area_verified = bool(area) and area in description
                    scope = dict(scope, area=area) if scope else {}
                    verified = verified and area_verified
                elif options['task_type'] == 'abyss' and scope and options.get('stage'):
                    if (scope.get('element') != options.get('element')
                            or scope.get('stage') not in (None, options['stage'])):
                        continue
                elif options['task_type'] == 'recollection':
                    if scope != dict(area=options.get('area'), floor=int(options['stage'])):
                        continue
                elif options['task_type'] in ('event', 'revival'):
                    area = options.get('area', '')
                    description = source.get('title', '')+' '+source.get('description', '')+' '+page_name
                    verified = verified and bool(area) and area in description
                    scope = dict(scope, area=area) if scope else {}
                # Full-name text rows and formation badges also occur outside battle.
                field_scope = scope if verified else {'chapters': requirement_scope(texts)}
                if options['task_type'] == 'subjugation':
                    if not verified:
                        field_scope = {'subjugation_cid': int(page['cid'])}
                    if not wide_crop and not combat_scene:
                        for row in requirement_cells(frame, texts, index):
                            evidence = Evidence(**{**asdict(proof), 'text': row['text'], 'rectangle': row['rectangle'],
                                                   'confidence': row['confidence'], 'method': 'avatar_labeled_cell'})
                            character_facts[row['name']].append((row['field'], row['value'], evidence, field_scope))
                for t in texts:
                    if t.score < .95:
                        continue
                    name = next((n for n in names if re.match(re.escape(n)+r'(?=[:：,，;；]|等级|Lv|LV|[1-6]星)', t.text)), None)
                    if name:
                        for field, value in labeled_fields(t.text[len(name):]).items():
                            evidence = Evidence(**{**asdict(proof), 'text': t.text, 'rectangle': list(t.rectangle), 'method': 'named_field', 'confidence': t.score})
                            character_facts[name].append((field, value, evidence, field_scope))
                for row in (formation_fields(frame, texts, index, badges) if not wide_crop else []):
                    evidence = Evidence(**{**asdict(proof), 'text': row['text'], 'rectangle': row['rectangle'], 'method': 'formation_badge', 'confidence': row['confidence']})
                    character_facts[row['name']].append((row['field'], row['value'], evidence, field_scope))
                if options['task_type'] == 'subjugation':
                    from .subjugation_guides import applicable_scope
                    if not applicable_scope(scope, options, allow_higher=True):
                        continue
                formation_found = False
                if not found:
                    found = formation_team(small, texts, index)
                    formation_found = bool(found)
                if not found and wide_crop:
                    found = wide_special_equipment_team(small, texts, index)
                    formation_found = bool(found)
                if not found and wide_crop and len(page_record.get('partial_card_rows', [])) < 2:
                    boxes = battle_rectangles(small, relaxed=True)
                    if len(boxes) == 5:
                        observed = [match_portrait(small, box, index) for box in boxes]
                        page_record.setdefault('partial_card_rows', []).append(dict(
                            image=str(image_path), slots=[dict(name=m['name'], score=m['score']) if m else None
                                                         for m in observed]))
                row = None
                if not found and not wide_crop and (requirements_page or any('一队通用' in t.text or '前三章' in t.text for t in texts)):
                    # Reuse the supported universal-table layout without calling OCR a second time.
                    from types import SimpleNamespace
                    result = SimpleNamespace(txts=[t.text for t in texts], scores=[t.score for t in texts],
                        boxes=np.asarray([[[x, y], [x+w, y], [x+w, y+h], [x, y+h]] for x, y, w, h in [t.rectangle for t in texts]]))
                    row = universal_row(frame, lambda _: result, index)
                    if row:
                        found = [dict(name=name, rectangle=[], score=proofs[0][1]) for name, proofs in zip(row['names'], row['confidence'])]
                        scope = dict(element=row['element'], chapters=row.get('chapters'))
                        verified = bool(scope['chapters'])
                if not found:
                    continue
                page_record['recognized_teams'] += 1
                key = json.dumps([scope, [m['name'] for m in found]], ensure_ascii=False, sort_keys=True)
                if key not in teams:
                    teams[key] = dict(task_type=options['task_type'], source=source['url'], scope=scope, scope_verified=verified,
                                      members=[empty_member(m['name']) for m in found], frames=[], observations=defaultdict(list),
                                      identity_evidence=[],
                                      auto=Fact(), auto_observations=[],
                                      notes=text_source, excluded_stages=[],
                                      global_requirements=[], manual_actions=[])
                team = teams[key]
                if options['task_type'] == 'subjugation' and verified:
                    from .subjugation_guides import damage_reference
                    reference = damage_reference(page, scope, subjugation_scope.maximum, source['url'])
                    if reference:
                        previous_reference = team.get('damage_reference')
                        if previous_reference and previous_reference['damage'] != reference['damage']:
                            team['damage_reference_conflict'] = True
                            team.pop('damage_reference', None)
                        elif not team.get('damage_reference_conflict'):
                            team['damage_reference'] = reference
                if scope_evidence and scope_evidence not in team.setdefault('scope_evidence', []):
                    team['scope_evidence'].append(scope_evidence)
                if row:
                    team['notes'] = '\n'.join(filter(None,(text_source,row.get('notes',''))))
                    team['excluded_stages'] = sorted(set(team['excluded_stages']) | set(row.get('excluded_stages',[])))
                team['frames'].append(asdict(proof))
                scaled_texts = texts_in_view(texts, raw.shape[1],
                                             crop_left if wide_crop else 0,
                                             crop_width if wide_crop else raw.shape[1])
                button_auto_texts = texts
                if not full_ocr and combat_boxes:
                    set_labels, auto_labels = combat_button_texts(
                        frame, small, combat_boxes, ocr, raw.shape[1],
                        crop_left if wide_crop else 0,
                        crop_width if wide_crop else raw.shape[1])
                    page_record['button_ocr_frames'] = page_record.get('button_ocr_frames', 0)+1
                    scaled_texts += set_labels
                    button_auto_texts = auto_labels
                    if not wide_crop:
                        scaled_texts += texts_in_view(auto_labels, raw.shape[1], 0, raw.shape[1])
                if not row:
                    # The wide video's combat cards need a central 16:9 crop,
                    # but its AUTO button remains visible on the uncropped edge.
                    team['auto_observations'].append((combat_auto(frame, button_auto_texts) if wide_crop
                                                      else combat_auto(small, scaled_texts),
                        Evidence(**{**asdict(proof), 'method':'combat_auto_button'})))
                for member, match in zip(team['members'], found):
                    rect = match['rectangle']
                    rectangle = ([round((crop_left+rect[0]*crop_width/960)*1280/raw.shape[1]), round(rect[1]*4/3),
                                  round(rect[2]*crop_width/960*1280/raw.shape[1]), round(rect[3]*4/3)] if wide_crop
                                 else [round(v*4/3) for v in rect])
                    p = Evidence(**{**asdict(proof), 'rectangle': rectangle,
                                    'method': 'avatar_feature_formation' if formation_found else 'avatar_feature',
                                    'confidence': match['score']})
                    team['identity_evidence'].append(dict(name=member['name'], **asdict(p)))
                    observations = team['observations'][member['name']]
                    if row:
                        i = row['names'].index(member['name'])
                        observations.extend([('instant', row['instant'][i], p), ('stars', row['required_stars'][i], p)])
                    elif not formation_found:
                        # Combat cards do not use the formation page's alternating
                        # sword/orb layout. Never infer UE absence from this view.
                        observations.append(('instant', combat_set(small, match, scaled_texts),
                            Evidence(**{**asdict(p), 'method':'combat_set_button'})))
        finally:
            capture.release()
    if options['task_type'] == 'subjugation':
        inspected = {p['cid']: p for p in pages_report}
        # A selected page with an unfamiliar title may still hold common
        # conditions. The later CID filter isolates only explicit other plans.
        for page in pages:
            record = inspected.get(page['cid'], {})
            if (record.get('readable_text_frames', 0) == 0 or record.get('skipped') or record.get('truncated')
                    or record.get('unread_frames') or record.get('unsupported_aspect')):
                title = page.get('part', page.get('title', ''))
                reason = '来源页面未完整解析：'+title
                globals_.append(dict(text=reason, advisory=False, evidence=asdict(Evidence(
                    source['url'], int(page['cid']), method='unread_requirements', text=reason))))
    # Named author statements can supply fields omitted by combat footage.
    # Only full, unambiguous names are accepted; base names never identify outfits.
    statements = []
    if options['task_type'] != 'subjugation':
        statements = [(source.get('description', ''), 'video_description')]
        statements.extend((r.get('text', ''), 'author_comment:'+str(r.get('reply_id'))) for r in source.get('author_comments', []))
    parties = []
    for team in teams.values():
        if len({(p['cid'], p['seconds']) for p in team['frames']}) < 2:
            continue
        if any(not any(row['name'] == member['name'] and row['confidence'] >= .92
                       for row in team['identity_evidence']) for member in team['members']):
            continue
        if options['task_type'] == 'subjugation':
            from .subjugation_guides import constraint_cids, plan_number
            cids = constraint_cids(pages, team['frames'])
            frame_cids = {frame['cid'] for frame in team['frames']}
            numbers = {plan_number(page) for page in pages if page['cid'] in frame_cids}
            build_rows = [r for r in metadata_build if (r['plan'] is None or not numbers
                          or None in numbers or r['plan'] in numbers)
                          and r['difficulty'] in (None, team['scope'].get('difficulty'))]
        chapter = team['scope'].get('chapters')
        auto_proofs = defaultdict(list)
        for value, proof in team.pop('auto_observations'):
            if value is not None:
                auto_proofs[value].append(proof)
        for value, proofs in auto_proofs.items():
            if len({(p.cid,p.seconds) for p in proofs}) >= 2:
                for proof in proofs:
                    team['auto'].add(value, proof)
        # Even one opposite button observation disqualifies a constant-AUTO
        # assumption; it remains evidence for Agent review, not a guessed axis.
        if len(auto_proofs) > 1:
            team['auto'] = Fact(conflicts=[dict(value=value, evidence=[asdict(p) for p in proofs])
                                          for value, proofs in auto_proofs.items()])
        for member in team['members']:
            observations = team['observations'][member['name']]
            for field, value, evidence, chapters in character_facts[member['name']]:
                if options['task_type'] == 'subjugation' and evidence.cid not in cids:
                    continue
                if options['task_type'] == 'subjugation' and isinstance(chapters, dict) and 'subjugation_cid' in chapters:
                    exact, chapters = chapters['subjugation_cid'] in cids, None
                elif isinstance(chapters, dict):
                    exact = bool(chapters) and all(team['scope'].get(k) == v for k, v in chapters.items())
                    chapters = chapters.get('chapters') if set(chapters) == {'chapters'} else None
                else:
                    exact = False
                if exact or (chapters and chapter and chapters[0] <= chapter[0] <= chapter[1] <= chapters[1]):
                    observations.append((field, value, evidence))
            # Confirmation is per value on distinct frames, never multiple crops of one frame.
            groups = defaultdict(list)
            for field, value, evidence in observations:
                if value is not None:
                    groups[(field, type(value).__name__, value)].append(evidence)
            for (field, _, value), proofs in groups.items():
                if len({(p.cid, p.seconds) for p in proofs}) >= 2:
                    for evidence in proofs:
                        member[field].add(value, evidence)
            for statement, method in statements:
                statement_scope = page_scope(source['pages'][0], options['task_type']) if len(source.get('pages', [])) == 1 else {}
                for line in statement.splitlines():
                    line = re.sub(r'\s+', '', line).replace('（', '(').replace('）', ')')
                    header_scope = page_scope({'part': line}, options['task_type'])
                    if header_scope:
                        statement_scope = header_scope
                    if not statement_scope or any(team['scope'].get(k) != v for k, v in statement_scope.items()):
                        continue
                    if re.match(re.escape(member['name'])+r'(?=[:：,，;；]|等级|Lv|LV|[1-6]星)', line):
                        for field, value in labeled_fields(line[len(member['name']):]).items():
                            member[field].add(value, Evidence(source['url'], method=method, text=line))
            if options['task_type'] == 'subjugation':
                for row in build_rows:
                    if row['name'] == member['name']:
                        for field, value in row['fields']:
                            member[field].add(value, Evidence(source['url'], method=row['method'], text=row['text']))
        team.pop('observations')
        team['region'] = source_region
        team['target_region'] = options.get('region', 'cn')
        if exact_full_set_claim(source, team['scope'], options['task_type']):
            proof = Evidence(source['url'], method='video_title_full_set', text=source['title'])
            for member in team['members']:
                member['instant'].add(True, proof)
        relevant_globals, relevant_manual = globals_, manual
        if options['task_type'] == 'subjugation':
            # Keep every selected notes page unless it explicitly belongs to
            # a different numbered plan. Absence of a recognized notes title
            # cannot remove an observed preparation or manual requirement.
            def applicable(row):
                evidence = row.get('evidence', {})
                return (evidence.get('cid') is None or evidence.get('cid') in cids
                        or evidence.get('method') in ('source_title', 'source_description', 'source_requirements'))
            relevant_globals = [r for r in globals_ if applicable(r)]
            relevant_manual = [r for r in manual if applicable(r)]
            relevant_globals.extend(dict(text=row['text'], advisory=False, evidence=asdict(Evidence(
                source['url'], method='unresolved_'+row['method'], text=row['text'])))
                for row in build_rows if row['name'] is None)
        team['global_requirements'] = list({r['text']: r for r in relevant_globals if not r['advisory']}.values())
        team['recommendations'] = list({r['text']: r for r in relevant_globals if r['advisory']}.values())
        team['manual_actions'] = list({r['text']: r for r in relevant_manual}.values())
        parties.append(finalize(team))
    from ..game_ui.screen import normalized
    for party in list(parties):
        if not party.get('scope_verified'):
            continue
        scope = party['scope']
        names = [normalized(m['name']) for m in party['members']]
        proofs = defaultdict(list)
        for row in records:
            if (row['difficulty'] == scope.get('difficulty')
                    and [normalized(m['name']) for m in row['members']] == names
                    and row['evidence']['cid'] in {p['cid'] for p in party['frames']}):
                proofs[row['mode']].append(row['evidence'])
        for mode, evidence in proofs.items():
            if mode != scope.get('mode') and len({(p['cid'], p['seconds']) for p in evidence}) >= 2:
                parties.append(finalize(dict(party, scope=dict(scope, mode=mode), mode_evidence=evidence)))
    report = dict(parser_version=PARSER_VERSION, fingerprint=fingerprint, parsed_at=time.time(),
                  source=source['url'], source_metadata=source, cache_hit=False, pages=pages_report, parties=parties,
                  character_requirements={name: [dict(field=k, value=v, evidence=asdict(p), chapters=c)
                                          for k, v, p, c in rows] for name, rows in character_facts.items()},
                  global_requirements=globals_, manual_actions=manual, errors=errors,
                  pending=[] if parties else ['未提取到至少两帧确认的五人阵容'],
                  status='complete' if parties and all(p['readiness'] == 'ready' for p in parties) and not errors else 'partial' if parties else 'blocked')
    atomic_json(cache, report)
    return report


def acquire_strategies(options: dict, *, api=None, index=None, ocr=None, check=lambda: None,
                       accept=None, exclude_sources=()) -> dict:
    """The shared GUI/CLI task path from public sources to evidence-backed files."""
    options = dict(options)
    exclude_sources = frozenset(exclude_sources)
    if options.get('task_type') not in ('abyss', 'dungeon', 'event', 'revival', 'recollection', 'subjugation'):
        raise ValueError('视频解析task_type必须为abyss、dungeon、event、revival、recollection或subjugation')
    for key, default, upper in [('max_videos', 4, 30), ('max_frames_per_page', 50, 300),
                                ('max_video_seconds', 180, 3600),
                                ('max_download_seconds', 180, 900),
                                ('parse_timeout', 900, 7200)]:
        value = options.setdefault(key, default)
        if type(value) is not int or not 1 <= value <= upper:
            raise ValueError(f'{key}必须为1到{upper}的整数')
    api = api or BilibiliApi(timeout=options.get('request_timeout', 20), browser_session=options.get('browser_session', True))
    report = dict(status='running', parties=[], parsed_sources=[], pending=[], errors=[])
    directory = Path(options.get('parsed_dir', 'cache/game/strategies/parsed'))
    scope = {k: options.get(k) for k in ('task_type', 'area', 'stage', 'element', 'difficulty', 'mode', 'region', 'source_urls', 'search_effort')}
    if options['task_type'] == 'subjugation':
        scope.update({k: options.get(k) for k in ('kind', 'boss', 'boss_number', 'event_id', 'period_start', 'period_end')})
    if exclude_sources:
        scope['exclude_sources'] = sorted(exclude_sources)
    output = directory/('catalog-'+sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()[:20]+'.json')
    started = time.monotonic()
    max_seconds = options.get('parse_timeout', 900)
    def bounded_check():
        check()
        if time.monotonic()-started > max_seconds:
            raise TimeoutError('攻略解析达到本次时间边界')
    try:
        if index is None:
            index, assets = ensure_avatar_index(options.get('avatars'), check=bounded_check)
            report['avatar_assets'] = {k: v for k, v in assets.items() if k != 'assets'}
        candidates = []
        preferred = []
        if options.get('source_urls'):
            preferred, errors = preferred_sources(options['source_urls'], api,
                        directory=options.get('source_cache_dir', 'cache/game/strategies/user_sources'),
                        timeout=options.get('request_timeout', 20), check=bounded_check,
                        require_complete_comments=options['task_type'] == 'subjugation',
                        max_comment_pages=options.get('max_comment_pages', 10))
            candidates.extend(p for p in preferred if p.get('user_provided', True))
            report['errors'].extend(errors)
        if options.get('search', True):
            catalog = discover_sources(options, api=api, check=bounded_check, exclude_sources=exclude_sources)
            report['search'] = catalog
            candidates.extend(catalog.get('candidates', []))
            candidates.extend(p for p in preferred if not p.get('user_provided', True))
            candidates.extend(catalog.get('preferred_sources', []))
        seen = set()
        parsed_count = 0
        for candidate in candidates:
            bounded_check()
            bvid = candidate.get('bvid')
            if not bvid or bvid in seen:
                continue
            url = f'https://www.bilibili.com/video/{bvid}/'
            if url in exclude_sources:
                continue
            if parsed_count >= options.get('max_videos', 4):
                break
            seen.add(bvid)
            report.setdefault('inspected_sources', []).append(url)
            try:
                # Both searched and supplied sources use the same canonical metadata schema.
                response = api.getVideoInfo(bvid=bvid)
                data = response.get('data', {})
                if response.get('code') != 0 or data.get('bvid') != bvid:
                    raise ValueError('视频身份不符')
                title, description = data.get('title', ''), data.get('desc', '')
                if not re.search(r'公主连[结接]|公主連[結接]|プリコネ|princess\s*connect|\bpcr\b', title+' '+description, re.I):
                    raise ValueError('来源未确认游戏身份')
                source = dict(provider='bilibili', bvid=bvid, url=f'https://www.bilibili.com/video/{bvid}/',
                              title=title, description=description, pages=data.get('pages', []),
                              published_at=data.get('pubdate'), author_comments=candidate.get('author_comments', []))
                if options['task_type'] == 'subjugation':
                    from .subjugation_guides import source_rejection
                    reason = source_rejection(source, options)
                    if reason:
                        report.setdefault('skipped_sources', []).append(dict(bvid=bvid, reason=reason))
                        continue
                    # Search hits use the same author-only supplement lookup
                    # as explicitly supplied links; never drop known conditions.
                    supplements, errors = preferred_sources([source['url']], api,
                        directory=options.get('source_cache_dir', 'cache/game/strategies/user_sources'),
                        timeout=options.get('request_timeout', 20), follow_comments=False,
                        require_complete_comments=True,max_comment_pages=options.get('max_comment_pages', 10),
                        check=bounded_check)
                    report['errors'].extend(errors)
                    if not supplements:
                        raise ValueError('作者评论补充未读取完成：没有来源返回')
                    supplement = supplements[0]
                    if (supplement.get('comment_pending') or supplement.get('comment_complete') is not True
                            or not supplement.get('comment_scope')
                            or not isinstance(supplement.get('author_comments'), list)):
                        raise ValueError('作者评论补充未读取完成：'+str(supplement.get('comment_pending') or '读取状态未知'))
                    source['author_comments'] = supplement['author_comments']
                    source['comment_scope'] = supplement['comment_scope']
                    source['comment_complete'] = True
                    source['comment_scan'] = supplement.get('comment_scan')
                if not choose_pages(source, options):
                    report.setdefault('skipped_sources', []).append(dict(bvid=bvid, reason='没有目标关卡候选分P'))
                    continue
                parsed_count += 1
                parsed = parse_video_source(source, options, index, api=api, ocr=ocr, check=bounded_check)
                report['parsed_sources'].append(parsed)
                if options['task_type'] == 'abyss' and options.get('stage'):
                    report['parties'].extend(p for p in parsed['parties']
                        if matches_abyss_request(p, options.get('element'), options['stage']))
                else:
                    report['parties'].extend(parsed['parties'])
                report['errors'].extend(parsed['errors'])
                if accept is not None and accept(report):
                    break
            except (requests.RequestException, RuntimeError, ValueError, OSError) as error:
                report['errors'].append(dict(bvid=bvid, error=str(error)))
        report['status'] = 'complete' if any(p['readiness'] == 'ready' for p in report['parties']) else 'partial' if report['parties'] else 'blocked'
        if report['status'] != 'complete':
            report['pending'].append('没有字段与适用范围全部明确的来源方案；详见逐角色pending，未用账号当前培养填补来源缺失')
    except (requests.RequestException, RuntimeError, ValueError, OSError) as error:
        report['status'] = 'blocked'
        report['errors'].append(dict(error=str(error)))
    report['document'] = str(output)
    export_document(output, report)
    return report
