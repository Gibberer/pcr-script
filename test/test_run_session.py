"""Offline tests: no emulator, no purchases, no real UI operations."""
import json
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
import subprocess
import sys
import numpy as np
from pcrscript.run_session import RunSession, TracedDriver, ResumeUnsafe, atomic_json, clock, failure, assert_inspection_allowed, _Tee


class Driver:
    def __init__(self):
        self.image = np.zeros((8, 8, 3), dtype=np.uint8)
        self.clicks = 0

    def screenshot(self):
        return self.image.copy()

    def click(self, *args):
        self.clicks += 1

    def input(self, text):
        pass


class RunSessionTests(unittest.TestCase):
    def test_retained_console_stream_after_log_closes(self):
        console, log = io.StringIO(), io.StringIO()
        stream = _Tee(console, log)
        stream.write('during session')
        stream.flush()
        self.assertEqual(log.getvalue(), 'during session')
        log.close()
        self.assertEqual(stream.write('after session'), len('after session'))
        stream.flush()
        self.assertEqual(console.getvalue(), 'during sessionafter session')

    def test_colorama_atexit_after_session(self):
        code = '''
import io, sys, tempfile
from pcrscript.run_session import RunSession
class Terminal(io.StringIO):
    def isatty(self): return True
sys.stdout = Terminal()
with tempfile.TemporaryDirectory() as root:
    with RunSession('exit-test', root) as run:
        import colorama
        colorama.init(strip=False, convert=False)
        print('task complete')
    assert 'task complete' in (run.path / 'console.log').read_text(encoding='utf-8')
sys.stdout = sys.__stdout__
'''
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code],
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    def test_control_cli_cross_process_and_exclusive_run(self):
        with tempfile.TemporaryDirectory() as root:
            code = '''
import sys, time
import numpy as np
from pcrscript.run_session import RunSession, TracedDriver
class Driver:
    def screenshot(self): return np.zeros((8,8,3), dtype=np.uint8)
with RunSession('child', sys.argv[1]) as run:
    driver = TracedDriver(Driver(), run)
    while not (run.path/'finish').exists():
        driver.screenshot()
        time.sleep(.02)
'''
            child = subprocess.Popen([sys.executable, '-X', 'utf8', '-c', code, root], stdout=subprocess.DEVNULL)
            try:
                deadline = time.monotonic()+10
                paths = []
                while not paths and time.monotonic() < deadline:
                    paths = list(Path(root).glob('*/status.json'))
                    time.sleep(.05)
                self.assertTrue(paths)
                run = paths[0].parent
                with self.assertRaisesRegex(RuntimeError, '尚未确认暂停'):
                    assert_inspection_allowed(root)
                for action, expected in [('pause', 'paused'), ('pause', 'paused'), ('snapshot', 'paused'), ('resume', 'running')]:
                    result = subprocess.run([sys.executable, '-X', 'utf8', 'scripts/agent/run_control.py',
                        action, '--run', str(run)], capture_output=True, text=True, encoding='utf-8', timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr+result.stdout)
                    self.assertEqual(json.loads(result.stdout)['state'], expected)
                    if expected == 'paused':
                        assert_inspection_allowed(root)
                with self.assertRaisesRegex(RuntimeError, '已有每日脚本'):
                    with RunSession('second', root):
                        pass
                (run/'finish').touch()
                self.assertEqual(child.wait(timeout=5), 0)
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)

    def test_error_preserves_traceback_and_frame_before_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(SystemExit):
                with RunSession('test', root) as run:
                    driver = TracedDriver(Driver(), run)
                    driver.screenshot()
                    try:
                        raise ValueError('temporary missing button')
                    except ValueError as error:
                        failure(error)
                    driver.driver.image[:] = 255
                    driver.screenshot()
            incident = next(run.path.glob('incident-*'))
            detail = json.loads((incident/'details.json').read_text(encoding='utf-8'))
            self.assertIn('ValueError: temporary missing button', detail['exception'])
            import cv2
            self.assertEqual(cv2.imread(str(incident/'last-observation.png')).max(), 0)
            self.assertEqual(json.loads((run.path/'status.json').read_text())['state'], 'failed')

    def pause_then_resume(self, run, change=None):
        atomic_json(run.path/'control.json', {'id': 'pause1', 'action': 'pause'})
        def control():
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                if run.state == 'paused':
                    break
                time.sleep(.01)
            else:
                return
            time.sleep(.15)
            if change:
                change()
            atomic_json(run.path/'control.json', {'id': 'resume1', 'action': 'resume'})
        worker = threading.Thread(target=control, daemon=True)
        worker.start()
        return worker

    def test_pause_ack_resume_and_timeout_clock(self):
        with tempfile.TemporaryDirectory() as root:
            with RunSession('test', root) as run:
                driver = TracedDriver(Driver(), run)
                driver.screenshot()
                active = clock.monotonic()
                wall = time.monotonic()
                worker = self.pause_then_resume(run)
                driver.click(1, 2)
                worker.join(3)
                self.assertEqual(driver.driver.clicks, 1)
                self.assertGreater(run.paused_seconds, .1)
                self.assertLess(clock.monotonic()-active, time.monotonic()-wall-.1)
                self.assertEqual(run.command_id, 'resume1')

    def test_changed_screen_does_not_execute_old_click(self):
        with tempfile.TemporaryDirectory() as root:
            with RunSession('test', root) as run:
                raw = Driver()
                driver = TracedDriver(raw, run)
                driver.screenshot()
                worker = self.pause_then_resume(run, lambda: raw.image.fill(255))
                with self.assertRaises(ResumeUnsafe):
                    driver.click(1, 2)
                worker.join(3)
                self.assertEqual(raw.clicks, 0)

    def test_snapshot_while_paused_does_not_resume(self):
        with tempfile.TemporaryDirectory() as root:
            with RunSession('test', root) as run:
                run.state = 'paused'
                atomic_json(run.path/'snapshot-request.json', {'id': 'snapshot1'})
                deadline = time.monotonic()+3
                while not run.snapshot_id and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertEqual(run.snapshot_id, 'snapshot1')
                self.assertEqual(run.state, 'paused')
                self.assertTrue(list(run.path.glob('incident-*/details.json')))

    def test_input_payload_is_not_logged(self):
        with tempfile.TemporaryDirectory() as root:
            with RunSession('test', root) as run:
                TracedDriver(Driver(), run).input('secret-password')
            self.assertNotIn('secret-password', (run.path/'events.jsonl').read_text())

    def test_watchdog_keeps_stack_without_driver_call(self):
        with tempfile.TemporaryDirectory() as root:
            with RunSession('test', root, stall_seconds=.05) as run:
                deadline = time.monotonic()+3
                while not list(run.path.glob('incident-*')) and time.monotonic()<deadline:
                    time.sleep(.05)
                details = next(run.path.glob('incident-*/details.json'))
                data = json.loads(details.read_text())
                self.assertIn('test_watchdog', data['owner_stack'])
                self.assertIsNone(data['frame_time'])


if __name__ == '__main__':
    unittest.main()
