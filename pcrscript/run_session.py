"""Local daily-run evidence and cooperative control; never operates UI from a thread."""
import contextlib
import json
import os
from pathlib import Path
import sys
import threading
import time as _time
import traceback
import uuid
import shutil

_current = None


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def emit(kind, **data):
    if _current:
        _current.event(kind, **data)


def failure(error):
    if _current:
        _current.incident('error', error)


def task_directory(name: str) -> Path | None:
    """Allocate evidence once per dispatched task, including repeated tasks."""
    if _current is None:
        return None
    import re
    _current.task_sequence = getattr(_current, 'task_sequence', 0) + 1
    safe_name = re.sub(r'[^\w.-]', '_', name)
    path = _current.path / 'tasks' / f'{_current.task_sequence:03d}-{safe_name}'
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_result(record: dict, directory: Path | None = None) -> None:
    emit('task.result', **record)
    if directory is not None:
        atomic_json(directory / 'result.json', record)


class _Clock:
    def sleep(self, seconds):
        if _current is None or threading.get_ident() != _current.owner:
            return _time.sleep(seconds)
        deadline = self.monotonic() + seconds
        while self.monotonic() < deadline:
            # Pause stays at driver boundaries so resume still checks stale pixels.
            if _current.command().get('action') == 'stop':
                _current.checkpoint()
            _time.sleep(min(.1, max(0, deadline - self.monotonic())))

    def time(self):
        return _time.time()

    def monotonic(self):
        return _time.monotonic() - (_current.paused_seconds if _current else 0)

    def __getattr__(self, name):
        return getattr(_time, name)


clock = _Clock()


def checkpoint():
    """Honor cooperative control during work that has no driver boundary."""
    if _current is not None and threading.get_ident() == _current.owner:
        _current.checkpoint()


class ResumeUnsafe(BaseException):
    """Must escape legacy catch-and-continue handlers before any stale click."""


class RunCancelled(BaseException):
    """Cooperative cancellation must escape task-level exception handlers."""


class _Tee:
    def __init__(self, stream, file):
        self.stream, self.file = stream, file

    def write(self, text):
        # Third-party loggers/colorama can retain this stream past the session,
        # including in atexit callbacks. The console remains usable then.
        if not self.file.closed:
            self.file.write(text)
            self.file.flush()
        return self.stream.write(text)

    def flush(self):
        if not self.file.closed:
            self.file.flush()
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


class RunSession:
    def __init__(self, name, root='cache/daily/runs', stall_seconds=120, run_id=None):
        if run_id is not None:
            run_id = str(uuid.UUID(run_id))
        self.path = Path(root) / (run_id or (_time.strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid()) + '-' + uuid.uuid4().hex[:6]))
        self.path.mkdir(parents=True)
        self.name = name
        self.stall_seconds = stall_seconds
        self.paused_seconds = 0
        self.state = 'running'
        self.last_activity = _time.monotonic()
        self.last_frame = None
        self.frame_time = None
        self.last_operation = None
        self.last_saved = 0
        self.frame_index = 0
        self.errors = 0
        self.command_id = None
        self.snapshot_id = None
        self.step = None
        self.progress = {'task': None, 'action': None}
        self.step_since = _time.monotonic()
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.owner = threading.get_ident()
        self.events = (self.path / 'events.jsonl').open('a', encoding='utf-8', buffering=1)

    def event(self, kind, **data):
        with self.lock:
            if kind == 'progress' and data.get('scope') in self.progress:
                scope = data['scope']
                self.progress[scope] = {key: value for key, value in data.items() if key != 'scope'}
                if scope == 'task':
                    self.progress['action'] = None
            if kind in ('task', 'action', 'wait'):
                step = (kind, json.dumps(data, ensure_ascii=False, default=str, sort_keys=True))
                if step != self.step:
                    self.step, self.step_since = step, _time.monotonic()
            self.events.write(json.dumps(dict(time=_time.time(), kind=kind, **data), ensure_ascii=False, default=str) + '\n')

    def status(self):
        with self.lock:
            atomic_json(self.path / 'status.json', dict(pid=os.getpid(), name=self.name, state=self.state,
                heartbeat=_time.time(), last_operation=self.last_operation, frame_time=self.frame_time,
                errors=self.errors, command_id=self.command_id, snapshot_id=self.snapshot_id,
                current_step=self.step, progress=self.progress, paused_seconds=self.paused_seconds))

    def frame(self, image):
        with self.lock:
            self.last_frame = image.copy()
            self.frame_time = _time.time()
            if _time.monotonic() - self.last_saved >= 5:
                self.frame_index += 1
                filename = f'frame-{self.frame_index % 24:02d}.png'
                self.save_image(self.path / filename, image)
                self.event('frame', file=filename, sequence=self.frame_index, captured_at=self.frame_time)
                self.last_saved = _time.monotonic()

    @staticmethod
    def save_image(path, image):
        import cv2
        ok, encoded = cv2.imencode('.png', image)
        if not ok:
            raise OSError('PNG encoding failed')
        encoded.tofile(path)

    def incident(self, reason, error=None):
        # Cached image: no concurrent driver calls, even when the driver is hung.
        with self.lock:
            if error is not None:
                self.errors += 1
            target = self.path / ('incident-' + _time.strftime('%H%M%S') + '-' + uuid.uuid4().hex[:6])
            target.mkdir()
            for frame in self.path.glob('frame-*.png'):
                shutil.copy2(frame, target / frame.name)
            if self.last_frame is not None:
                self.save_image(target / 'last-observation.png', self.last_frame)
            stack = sys._current_frames().get(self.owner)
            detail = dict(reason=reason, time=_time.time(), frame_time=self.frame_time,
                screenshot_kind='last successful observation; may be stale',
                last_operation=self.last_operation,
                current_step=self.step,
                exception=''.join(traceback.format_exception(type(error), error, error.__traceback__)) if error else None,
                owner_stack=''.join(traceback.format_stack(stack)) if stack else None)
            atomic_json(target / 'details.json', detail)
            self.event('incident', directory=target.name, reason=reason)

    def command(self):
        try:
            return json.loads((self.path / 'control.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def checkpoint(self):
        command = self.command()
        if command.get('action') == 'stop' and command.get('id') != self.command_id:
            self.command_id = command['id']
            raise RunCancelled('用户请求停止任务')
        if command.get('id') == self.command_id or command.get('action') != 'pause':
            return False
        start = _time.monotonic()
        with self.lock:
            self.command_id = command['id']
            self.state = 'paused'
            self.event('paused')
            self.status()
        while not self.stop.wait(.1):
            command = self.command()
            if command.get('action') == 'stop' and command.get('id') != self.command_id:
                self.command_id = command['id']
                raise RunCancelled('用户请求停止任务')
            if command.get('action') == 'resume' and command.get('id') != self.command_id:
                break
        with self.lock:
            duration = _time.monotonic() - start
            self.paused_seconds += duration
            self.step_since += duration
            self.command_id = command.get('id')
            self.state = 'running'
            self.last_activity = _time.monotonic()
            self.event('resumed')
            self.status()
        return True

    def watch(self):
        warned = False
        while not self.stop.wait(1):
            try:
                try:
                    command = json.loads((self.path / 'snapshot-request.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    command = {}
                if command.get('id') and command['id'] != self.snapshot_id:
                    self.incident('requested snapshot')
                    self.snapshot_id = command['id']
                stalled = self.state == 'running' and (
                    _time.monotonic() - self.last_activity > self.stall_seconds or
                    self.step is not None and _time.monotonic() - self.step_since > 300)
                if stalled and not warned:
                    self.incident('suspected stall: no driver completion or same step for 300s; inspect stack')
                warned = stalled
                self.status()
            except Exception as error:
                print(f'[run diagnostics] {error}', file=sys.stderr)

    def __enter__(self):
        global _current
        if _current:
            raise RuntimeError('nested RunSession')
        # One production automation process per checkout, including startup.
        import msvcrt
        self.run_lock = (self.path.parent / 'daily.lock').open('a+b')
        self.run_lock.seek(0)
        try:
            msvcrt.locking(self.run_lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.run_lock.close()
            self.events.close()
            raise RuntimeError('已有每日脚本运行；请先用 run_control.py 查询/暂停')
        _current = self
        self.console = (self.path / 'console.log').open('a', encoding='utf-8', buffering=1)
        self.redirect = contextlib.ExitStack()
        self.redirect.enter_context(contextlib.redirect_stdout(_Tee(sys.stdout, self.console)))
        self.redirect.enter_context(contextlib.redirect_stderr(_Tee(sys.stderr, self.console)))
        self.event('start', name=self.name, python=sys.version)
        print(f'[运行记录] {self.path.resolve()}', flush=True)
        self.status()
        self.thread = threading.Thread(target=self.watch, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, kind, error, tb):
        global _current
        self.stop.set()
        self.thread.join(timeout=2)
        try:
            if error is not None and not isinstance(error, RunCancelled) and not (isinstance(error, SystemExit) and error.code in (None, 0)):
                self.incident('uncaught exception', error)
            self.state = 'cancelled' if isinstance(error, RunCancelled) else ('failed' if self.errors else 'finished')
            self.event('end', state=self.state)
            self.status()
        finally:
            _current = None
            self.redirect.close()
            self.console.close()
            self.events.close()
            self.run_lock.close()
        if error is None and self.errors:
            raise SystemExit(1)
        return isinstance(error, RunCancelled)


class TracedDriver:
    def __init__(self, driver, session):
        self.driver, self.session = driver, session

    def __getattr__(self, name):
        return getattr(self.driver, name)

    def _call(self, name, *args, **kwargs):
        run = self.session
        resumed = run.checkpoint()
        if resumed and name in ('click', 'swipe', 'input'):
            # A suspended action was computed from the old observation. Require
            # exact equality; animated screens can conservatively stop the run.
            import numpy as np
            now = self.driver.screenshot()
            same = run.last_frame is not None and np.array_equal(now, run.last_frame)
            run.frame(now)
            if not same:
                raise ResumeUnsafe('暂停期间画面发生变化，已停止旧操作；请重新运行任务以重新识别页面')
        run.last_operation = name
        data = {} if name == 'input' else dict(args=args, kwargs=kwargs)
        run.event('driver.begin', operation=name, **data)
        try:
            result = getattr(self.driver, name)(*args, **kwargs)
            if name == 'screenshot':
                if result is None or not result.size:
                    raise RuntimeError('empty driver screenshot')
                run.frame(result)
            run.last_activity = _time.monotonic()
            run.event('driver.end', operation=name)
            return result
        except Exception as error:
            run.incident('driver exception', error)
            raise

    def screenshot(self, *args, **kwargs):
        return self._call('screenshot', *args, **kwargs)

    def click(self, *args, **kwargs):
        return self._call('click', *args, **kwargs)

    def swipe(self, *args, **kwargs):
        return self._call('swipe', *args, **kwargs)

    def input(self, *args, **kwargs):
        return self._call('input', *args, **kwargs)


def wrap_driver(driver):
    return TracedDriver(driver, _current) if _current and not isinstance(driver, TracedDriver) else driver


def assert_inspection_allowed(root='cache/daily/runs'):
    """Guard standard Agent tools. Resume only after the inspection exits."""
    import msvcrt
    root = Path(root)
    path = root / 'daily.lock'
    if not path.exists():
        return
    with path.open('r+b') as handle:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            states = []
            for file in root.glob('*/status.json'):
                try:
                    state = json.loads(file.read_text(encoding='utf-8'))
                    if state['state'] in ('running', 'paused') and _time.time()-state['heartbeat'] < 10:
                        states.append(state)
                except (OSError, ValueError, KeyError):
                    continue
            if len(states) != 1 or states[0]['state'] != 'paused':
                raise RuntimeError('每日脚本尚未确认暂停；禁止同时探查模拟器')
