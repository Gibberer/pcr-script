"""Offline avatar timing only; does not validate recognition accuracy or open the game."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--threads', type=int, default=0, help='0 keeps the current library defaults')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.threads:
        for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
            os.environ[key] = str(args.threads)
    import cv2 as cv
    import numpy as np

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('avatar_benchmark_module', root/'pcrscript/game_ui/avatars.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    start = time.perf_counter()
    index = module.AvatarIndex(root/'cache/game/avatars')
    first_load = (time.perf_counter()-start)*1000
    if not index.names:
        raise RuntimeError('Existing avatar index required; benchmark never downloads or modifies it')
    files = sorted((root/'cache/character').glob('*.webp'))
    if len(files) < 5:
        raise RuntimeError('At least five existing public avatar images required')
    icons = [cv.imdecode(np.fromfile(path, np.uint8), cv.IMREAD_COLOR) for path in files]
    if any(icon is None for icon in icons):
        raise RuntimeError('Unreadable public avatar image')
    faces = [module.face_crop(icon, (0, 0, icon.shape[1], icon.shape[0])) for icon in icons]
    queries = [faces[i] for i in np.linspace(0, len(faces)-1, 5, dtype=int)]
    vectors = np.stack([module.feature(face) for face in queries])
    matrix = index.matrix
    timings = {}

    def measure(name, call, minimum=10, maximum=500, seconds=.4):
        call()
        values = []
        started = time.perf_counter()
        while len(values) < maximum:
            begin = time.perf_counter_ns()
            call()
            values.append((time.perf_counter_ns()-begin)/1e6)
            if len(values) >= minimum and time.perf_counter()-started >= seconds:
                break
        result = dict(median_ms=float(np.median(values)), p95_ms=float(np.percentile(values, 95)),
                      min_ms=min(values), samples=len(values))
        timings[name] = result
        print(name, json.dumps(result), flush=True)

    # Equal mathematical operation: only replace Python per-template dispatch with matrix multiplication.
    def loop_scores():
        return np.asarray([[float(reference @ query) for reference in matrix] for query in vectors])

    batch_scores = vectors @ matrix.T
    loop_result = loop_scores()
    max_difference = float(np.max(np.abs(batch_scores-loop_result)))
    if not np.allclose(batch_scores, loop_result, atol=2e-6):
        raise AssertionError('Loop and batch scores disagree')

    measure('index_load_from_existing_npz', lambda: module.AvatarIndex(root/'cache/game/avatars'), maximum=30)
    measure('feature_extract_1', lambda: module.feature(queries[0]))
    measure('feature_extract_5', lambda: np.stack([module.feature(p) for p in queries]))
    measure('cached_features_python_loop_scores_5', loop_scores, maximum=100)
    measure('cached_features_matrix_scores_1', lambda: vectors[:1] @ matrix.T)
    measure('cached_features_matrix_scores_5', lambda: vectors @ matrix.T)
    measure('production_query_1', lambda: index.query(queries[:1]))
    measure('production_query_5', lambda: index.query(queries))
    measure('production_query_5_separate_calls', lambda: [index.query([p]) for p in queries])

    def rebuild_gallery():
        return np.stack([module.feature(p) for p in faces])

    def disk_rebuild_gallery():
        result = []
        for path in files:
            icon = cv.imdecode(np.fromfile(path, np.uint8), cv.IMREAD_COLOR)
            result.append(module.feature(module.face_crop(icon, (0, 0, icon.shape[1], icon.shape[0]))))
        return np.stack(result)

    measure('extract_gallery_features_from_decoded_images', rebuild_gallery, maximum=30)
    measure('read_decode_extract_gallery', disk_rebuild_gallery, minimum=3, maximum=5)

    # Reproduce the video parser's 125 crop/size hypotheses per avatar, five avatars.
    # Uses existing public images: timing workload, not a video accuracy evaluation.
    patches = [cv.copyMakeBorder(cv.resize(p, (96, 96)), 4, 4, 4, 4, cv.BORDER_REFLECT) for p in queries]
    def crop_vectors(patch):
        return np.stack([module.feature(module.face_crop(patch, (4+dx, 4+dy, 96+ds, 96+ds)))
                         for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)
                         for ds in (-2, -1, 0, 1, 2)])

    variants = [crop_vectors(patch) for patch in patches]
    measure('video_625_hypotheses_features_only', lambda: [crop_vectors(p) for p in patches], maximum=100)
    measure('video_625_hypotheses_scores_only', lambda: [(v @ matrix.T).max(axis=0) for v in variants], maximum=100)
    def video_workload():
        result = []
        for patch in patches:
            scores = (crop_vectors(patch) @ matrix.T).max(axis=0)
            best = {}
            for i in np.argsort(scores)[::-1]:
                best.setdefault(str(index.names[i]), float(scores[i]))
                if len(best) == 2:
                    break
            result.append(best)
        return result
    measure('video_625_hypotheses_extract_score_rank', video_workload, maximum=100)

    config = io.StringIO()
    with contextlib.redirect_stdout(config):
        np.show_config()
    cpu = platform.processor()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            cpu = winreg.QueryValueEx(key, 'ProcessorNameString')[0]
    except OSError:
        pass
    report = dict(created_at=time.strftime('%Y-%m-%d %H:%M:%S %z'), cpu=cpu, logical_cpus=os.cpu_count(),
                  python=sys.version, numpy=np.__version__, opencv=cv.__version__, threads_requested=args.threads,
                  thread_environment={k: os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')},
                  numpy_config=config.getvalue(), features=matrix.shape[0], dimensions=matrix.shape[1],
                  identities=len(set(index.names)), matrix_mib=matrix.nbytes/1024**2,
                  public_icon_files=len(files), first_observed_index_load_ms=first_load,
                  loop_batch_max_abs_difference=max_difference, timings=timings,
                  limitations=['Existing cached public images, no accuracy measurement',
                               'OS file cache was not flushed; file reads are warm-cache measurements',
                               'No video decoding, OCR, download, UI navigation or YOLO inference included',
                               'Video workload is one spacing pass, up to three are possible in current parser'])
    output = root/args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('cpu', 'features', 'dimensions', 'identities', 'matrix_mib', 'public_icon_files')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
