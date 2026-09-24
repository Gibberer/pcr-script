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
from .strategy_sources import MANUAL_PART, UNVERIFIED_SETTING, discover_sources
from .strategy_inputs import preferred_sources

PARSER_VERSION = 24
FRAME_OCR_VERSION = 1
ELEMENTS = {'火': 'fire', '水': 'water', '风': 'wind', '光': 'light', '暗': 'dark',
            '红焰': 'fire', '苍波': 'water', '翠岚': 'wind', '珀天': 'light', '紫冥': 'dark'}


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
    """Include short-lived opening formation/equipment screens in wide videos."""
    early = [s for s in ([.5, 1.5, 2.0, 3.5] if wide else [.5, 1.5]) if s < duration]
    regular_count = max(0, maximum-len(early))
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
    else:
        raise ValueError('未知攻略任务类型')
    return result


def page_scope(page: dict, kind: str) -> dict:
    title = page.get('part', page.get('title', ''))
    if kind == 'abyss':
        match = re.search(r'(红焰|苍波|翠岚|珀天|紫冥|火|水|风|光|暗)(?:深域)?\s*(\d+)\s*[-－]\s*(\d+)(?!\d|图)', title)
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
        difficulty = ('special_plus' if re.search(r'特别战斗\s*[＋+]|SP\s*\+', title, re.I)
                      else 'special' if re.search(r'特别战斗|(?:^|\W)SP(?:\W|$)', title, re.I)
                      else 'very_hard' if re.search(r'高难|VERY\s*HARD|(?:^|\W)VH(?:\W|$)', title, re.I)
                      else None)
        phase = re.search(r'(?:模式|MODE|阶段)\s*([123])', title, re.I)
        if difficulty and phase:
            return dict(difficulty=difficulty, mode=int(phase[1]))
    return {}


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
    elif kind in ('event', 'revival'):
        wanted = {'difficulty': options.get('difficulty'), 'mode': options.get('mode')}
        targets = [p for p in pages if (scope := page_scope(p, kind)) == wanted]
        if not targets and len(pages) == 1 and page_scope({'part': source.get('title', '')}, kind) == wanted:
            targets = [dict(pages[0], part=source['title'])]
        # An unlabeled page can still prove its scope from visible battle text.
        chosen_cids = {p.get('cid') for p in targets}
        targets += [p for p in pages if p not in requirements and p.get('cid') not in chosen_cids
                    and not page_scope(p, kind)]
    else:
        targets = [p for p in pages if p not in requirements]
    limit = options.get('max_pages_per_video', 4)
    if type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError('max_pages_per_video必须为1到30')
    # Reserve at least one position for actual combat, even in large requirements collections.
    return requirements[:max(0, limit-1)]+targets[:max(1, limit-len(requirements[:max(0, limit-1)]))]


def declared_region(text: str) -> str:
    values = {code for code, pattern in [('cn', '国服|國服'), ('jp', '日服'), ('tw', '台服|臺服')]
              if re.search(pattern, text)}
    return next(iter(values)) if len(values) == 1 else 'conflict' if values else 'unknown'


def observed_scope(texts, page: dict, kind: str) -> tuple[dict, bool]:
    metadata = page_scope(page, kind)
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
        if re.search(r'手动|目押|卡[秒帧]|连点|关闭自动|关AUTO|轴[:：]|改星|调星|切星|降星|星级变更|\d[:：]\d{2}.*(?:开|关|点|放)', t.text, re.I):
            manual.append(row)
    return global_requirements, manual


def parse_video_source(source: dict, options: dict, index, *, api=None, ocr=None,
                       media_fetcher=fetch_video, check=lambda: None) -> dict:
    """Return candidates plus field evidence, including incomplete/contradictory ones."""
    from rapidocr import RapidOCR
    from .strategy_tables import universal_row
    api = api or BilibiliApi(timeout=options.get('request_timeout', 20), browser_session=True)
    root = Path(options.get('parsed_dir', 'cache/game/strategies/parsed'))/source['bvid']
    root.mkdir(parents=True, exist_ok=True)
    pages = choose_pages(source, options)
    fingerprint = sha256(json.dumps(dict(version=PARSER_VERSION, source=source, pages=pages,
                         scope={k: options.get(k) for k in ('task_type', 'stage', 'element', 'area', 'difficulty', 'mode', 'region', 'max_frames_per_page', 'max_video_seconds', 'skip_manual_media', 'skip_long_media')},
                         index=sha256(index.matrix.tobytes()+json.dumps(index.names, ensure_ascii=False).encode()).hexdigest()), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    cache = root/(fingerprint[:24]+'.json')
    saved = read_json(cache)
    if saved.get('fingerprint') == fingerprint and not saved.get('errors') and saved.get('parties') and 0 <= time.time()-saved.get('parsed_at', 0) < options.get('max_age_hours', 24)*3600:
        paths = [e.get('image') for p in saved.get('parties', []) for m in p['members']
                 for key in ('stars', 'unique', 'unique2', 'instant') for e in m[key].get('evidence', []) if e.get('image')]
        if all(Path(p).is_file() for p in paths):
            return dict(saved, cache_hit=True)
    ocr = ocr or RapidOCR()
    from ..game_ui.equipment import EquipmentBadges
    badges = EquipmentBadges()
    names = sorted({str(n) for n in index.names if not str(n).startswith('unit:')}, key=len, reverse=True)
    teams = {}
    character_facts = defaultdict(list)
    globals_, manual = [], []
    errors, pages_report = [], []
    source_region = declared_region(source.get('title', '')+' '+source.get('description', ''))
    text_source = '\n'.join([source.get('description', '')]+[r.get('text', '') for r in source.get('author_comments', [])])
    source_setting = UNVERIFIED_SETTING.search(source.get('description') or '')
    if source_setting:
        description = source.get('description') or ''
        manual.append(dict(text=description[:240], evidence=asdict(Evidence(
            source['url'], int(pages[0]['cid']) if pages else 0,
            method='source_description', text=description[:240]))))
    for page in pages:
        check()
        page_name = page.get('part', page.get('title', ''))
        requirements_page = bool(re.search(r'练度|培养|角色需求|配置要求', page_name))
        original_part = page.get('original_part', page_name)
        manual_part = bool(MANUAL_PART.search(original_part))
        if manual_part:
            manual.append(dict(text=original_part, evidence=asdict(Evidence(
                source['url'], int(page['cid']), method='part_title', text=original_part))))
            if options.get('skip_manual_media'):
                pages_report.append(dict(cid=page['cid'], title=page_name,
                                         skipped='标题要求手动操作或未核实TP+2，自动任务不下载此分P'))
                continue
        if source_setting and options.get('skip_manual_media'):
            pages_report.append(dict(cid=page['cid'], title=page_name,
                                     skipped='简介含未核实TP+2大师点条件，自动任务不下载此分P'))
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
                                       timeout=options.get('request_timeout', 20), check=check)
        except (requests.RequestException, RuntimeError, ValueError, OSError) as error:
            errors.append(dict(cid=page['cid'], error=str(error)))
            continue
        capture = cv.VideoCapture(str(video))
        page_record = dict(cid=page['cid'], title=page_name, media=media, frames=0, recognized_teams=0)
        pages_report.append(page_record)
        duration = min(float(page.get('duration') or media['duration']), float(options.get('max_video_seconds', 180)))
        wide = media.get('height', 0) > 0 and 1.9 < media.get('width', 0)/media['height'] <= 2.4
        seconds_list = sample_seconds(duration, options.get('max_frames_per_page', 50), wide=wide)
        previous = None
        last_scope = ({}, False)
        try:
            for seconds in seconds_list:
                check()
                capture.set(cv.CAP_PROP_POS_MSEC, float(seconds)*1000)
                ok, raw = capture.read()
                if not ok:
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
                texts = frame_texts(frame, image_path, ocr)
                page_record['frames'] += 1
                proof = Evidence(source['url'], int(page['cid']), float(seconds), str(image_path), method='video_ocr')
                detected_region = declared_region('\n'.join(t.text for t in texts if t.score >= .95))
                if detected_region != 'unknown':
                    source_region = detected_region if source_region == 'unknown' else source_region if source_region == detected_region else 'conflict'
                global_rows, manual_rows = text_constraints(texts, proof)
                globals_.extend(global_rows)
                manual.extend(manual_rows)
                if not wide_crop and (requirements_page or any('角色需求' in t.text or '练度' in t.text for t in texts)):
                    chapter_scope = requirement_scope(texts)
                    for row in requirement_cells(frame, texts, index):
                        evidence = Evidence(**{**asdict(proof), 'text': row['text'], 'rectangle': row['rectangle'],
                                               'confidence': row['confidence'], 'method': 'avatar_labeled_cell'})
                        character_facts[row['name']].append((row['field'], row['value'], evidence, chapter_scope))
                scope, verified = observed_scope(texts, page, options['task_type'])
                if scope and not verified:
                    # Conflicting visible stage labels must invalidate the frame.
                    last_scope = ({}, False)
                    continue
                if verified:
                    last_scope = scope, verified
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
                elif options['task_type'] in ('event', 'revival'):
                    area = options.get('area', '')
                    description = source.get('title', '')+' '+source.get('description', '')+' '+page_name
                    verified = verified and bool(area) and area in description
                    scope = dict(scope, area=area) if scope else {}
                # Full-name text rows and formation badges also occur outside battle.
                field_scope = scope if verified else {'chapters': requirement_scope(texts)}
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
                found = combat_team(small, index, relaxed=wide_crop)
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
                    teams[key] = dict(source=source['url'], scope=scope, scope_verified=verified,
                                      members=[empty_member(m['name']) for m in found], frames=[], observations=defaultdict(list),
                                      identity_evidence=[],
                                      auto=Fact(), auto_observations=[],
                                      notes=text_source, excluded_stages=[],
                                      global_requirements=[], manual_actions=[])
                team = teams[key]
                if row:
                    team['notes'] = '\n'.join(filter(None,(text_source,row.get('notes',''))))
                    team['excluded_stages'] = sorted(set(team['excluded_stages']) | set(row.get('excluded_stages',[])))
                team['frames'].append(asdict(proof))
                scaled_texts = texts_in_view(texts, raw.shape[1],
                                             crop_left if wide_crop else 0,
                                             crop_width if wide_crop else raw.shape[1])
                if not row:
                    # The wide video's combat cards need a central 16:9 crop,
                    # but its AUTO button remains visible on the uncropped edge.
                    team['auto_observations'].append((combat_auto(frame, texts) if wide_crop
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
    # Named author statements can supply fields omitted by combat footage.
    # Only full, unambiguous names are accepted; base names never identify outfits.
    statements = [(source.get('description', ''), 'video_description')]
    statements.extend((r.get('text', ''), 'author_comment:'+str(r.get('reply_id'))) for r in source.get('author_comments', []))
    parties = []
    for team in teams.values():
        if len({(p['cid'], p['seconds']) for p in team['frames']}) < 2:
            continue
        if any(not any(row['name'] == member['name'] and row['confidence'] >= .92
                       for row in team['identity_evidence']) for member in team['members']):
            continue
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
                if isinstance(chapters, dict):
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
        team.pop('observations')
        team['region'] = source_region
        team['target_region'] = options.get('region', 'cn')
        team['global_requirements'] = list({r['text']: r for r in globals_ if not r['advisory']}.values())
        team['recommendations'] = list({r['text']: r for r in globals_ if r['advisory']}.values())
        team['manual_actions'] = list({r['text']: r for r in manual}.values())
        parties.append(finalize(team))
    report = dict(parser_version=PARSER_VERSION, fingerprint=fingerprint, parsed_at=time.time(),
                  source=source['url'], source_metadata=source, cache_hit=False, pages=pages_report, parties=parties,
                  character_requirements={name: [dict(field=k, value=v, evidence=asdict(p), chapters=c)
                                          for k, v, p, c in rows] for name, rows in character_facts.items()},
                  global_requirements=globals_, manual_actions=manual, errors=errors,
                  pending=[] if parties else ['未提取到至少两帧确认的五人阵容'],
                  status='complete' if parties and all(p['readiness'] == 'ready' for p in parties) and not errors else 'partial' if parties else 'blocked')
    atomic_json(cache, report)
    return report


def acquire_strategies(options: dict, *, api=None, index=None, ocr=None, check=lambda: None) -> dict:
    """The shared GUI/CLI task path from public sources to evidence-backed files."""
    options = dict(options)
    if options.get('task_type') not in ('abyss', 'dungeon', 'event', 'revival'):
        raise ValueError('视频解析task_type必须为abyss、dungeon、event或revival')
    for key, default, upper in [('max_videos', 4, 30), ('max_frames_per_page', 50, 300),
                                ('max_video_seconds', 180, 3600), ('parse_timeout', 900, 7200)]:
        value = options.setdefault(key, default)
        if type(value) is not int or not 1 <= value <= upper:
            raise ValueError(f'{key}必须为1到{upper}的整数')
    api = api or BilibiliApi(timeout=options.get('request_timeout', 20), browser_session=options.get('browser_session', True))
    report = dict(status='running', parties=[], parsed_sources=[], pending=[], errors=[])
    directory = Path(options.get('parsed_dir', 'cache/game/strategies/parsed'))
    scope = {k: options.get(k) for k in ('task_type', 'area', 'stage', 'element', 'difficulty', 'mode', 'region', 'source_urls')}
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
                        timeout=options.get('request_timeout', 20))
            candidates.extend(p for p in preferred if p.get('user_provided', True))
            report['errors'].extend(errors)
        if options.get('search', True):
            catalog = discover_sources(options, api=api)
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
            if parsed_count >= options.get('max_videos', 4):
                break
            seen.add(bvid)
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
