"""Measure avatar matching on a local video with explicitly calibrated rectangles.

This diagnostic does not locate portraits automatically or validate team builds.
Rectangles are [x, y, width, height] in a normalized 960x540 frame.
"""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import time

import cv2 as cv
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True)
    parser.add_argument('--rectangles', required=True, help='JSON file containing five rectangles')
    parser.add_argument('--output', required=True)
    parser.add_argument('--start', type=float, default=6)
    parser.add_argument('--stop', type=float, default=60)
    parser.add_argument('--step', type=float, default=2)
    args = parser.parse_args()
    if args.step <= 0 or not 0 <= args.start < args.stop:
        parser.error('Require 0 <= start < stop and step > 0')
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('avatar_probe_module', root/'pcrscript/game_ui/avatars.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rectangles = json.loads(Path(args.rectangles).read_text(encoding='utf-8'))
    if len(rectangles) != 5 or any(len(r) != 4 or min(r) < 0 or min(r[2:]) == 0
                                 or r[0]+r[2] > 960 or r[1]+r[3] > 540 for r in rectangles):
        parser.error('Expected five valid rectangles within 960x540')
    index = module.AvatarIndex(root/'cache/game/avatars')
    if len(set(index.names)) < 2:
        raise RuntimeError('Existing reference index with multiple identities required')
    capture = cv.VideoCapture(str(Path(args.video).resolve()))
    if not capture.isOpened():
        raise RuntimeError('Cannot open the local video')
    records = []
    try:
        for seconds in np.arange(args.start, args.stop, args.step):
            decode_start = time.perf_counter()
            capture.set(cv.CAP_PROP_POS_MSEC, float(seconds)*1000)
            ok, frame = capture.read()
            if not ok:
                records.append(dict(seconds=float(seconds), decoded=False))
                continue
            frame = cv.resize(frame, (960, 540))
            decode_ms = (time.perf_counter()-decode_start)*1000
            begin = time.perf_counter()
            vectors = np.stack([module.feature(module.face_crop(frame, r)) for r in rectangles])
            scores = vectors @ index.matrix.T
            slots = []
            for row in scores:
                best = {}
                for i in np.argsort(row)[::-1]:
                    best.setdefault(str(index.names[i]), float(row[i]))
                    if len(best) == 2:
                        break
                pairs = list(best.items())
                gap = pairs[0][1]-pairs[1][1]
                slots.append(dict(top=pairs[0][0], score=pairs[0][1], second=pairs[1][0], gap=gap,
                                  accepted=pairs[0][1] >= .92 and gap >= .06))
            ms = (time.perf_counter()-begin)*1000
            names = [s['top'] for s in slots]
            records.append(dict(seconds=float(seconds), decoded=True, slots=slots,
                                matching_ms=ms, seek_decode_resize_ms=decode_ms,
                                full_team_accepted=all(s['accepted'] for s in slots)
                                and len(set(names)) == 5 and not any(n.startswith('unit:') for n in names)))
    finally:
        capture.release()
    decoded = [r for r in records if r.get('decoded')]
    if not decoded:
        raise RuntimeError('No frames decoded')
    teams = Counter(tuple(s['top'] for s in r['slots']) for r in decoded if r['full_team_accepted'])
    summary = dict(sampled_frames=len(records), decoded_frames=len(decoded),
                   full_team_accepted_frames=sum(teams.values()),
                   accepted_teams=[dict(names=list(team), frames=count) for team, count in teams.most_common()],
                   matching_median_ms=float(np.median([r['matching_ms'] for r in decoded])),
                   matching_p95_ms=float(np.percentile([r['matching_ms'] for r in decoded], 95)),
                   seek_decode_resize_median_ms=float(np.median([r['seek_decode_resize_ms'] for r in decoded])))
    report = dict(video=str(Path(args.video).resolve()), rectangles=rectangles,
                  thresholds=dict(score=.92, different_identity_margin=.06), summary=summary, frames=records,
                  limitations=['Manual layout calibration; not automatic avatar detection',
                               'Consistency is not an independently labeled accuracy metric',
                               'No cultivation, SET, scope or victory verification',
                               'Portrait absence/occlusion is not explicitly classified by this probe'])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
