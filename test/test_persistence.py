"""Atomic state/cache writes preserve the last record on failure."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from pcrscript import run_session
from pcrscript.run_session import atomic_json


class PersistenceTests(TestCase):
    def test_write_creates_parent_and_preserves_unicode(self):
        with TemporaryDirectory() as root:
            path = Path(root) / 'new' / 'state.json'
            atomic_json(str(path), {'pending': ['合成消费']})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'pending': ['合成消费']})
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_windows_sharing_denial_retries_then_replaces(self):
        for winerror in (5, 32):
            with self.subTest(winerror=winerror), TemporaryDirectory() as root:
                path = Path(root) / 'state.json'
                attempts = []

                def busy_twice(source, target):
                    attempts.append(source)
                    if len(attempts) < 3:
                        error = PermissionError('temporarily busy')
                        error.winerror = winerror
                        raise error
                    return os.replace(source, target)

                with patch.object(run_session, 'os', SimpleNamespace(name='nt', replace=busy_twice)), \
                     patch.object(run_session._time, 'sleep') as sleep:
                    atomic_json(path, {'state': 'running'})
                self.assertEqual(len(attempts), 3)
                self.assertEqual(sleep.call_count, 2)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'state': 'running'})
                self.assertEqual(list(path.parent.iterdir()), [path])

    def test_failed_replace_preserves_old_record_and_cleans_temporary_file(self):
        for platform, winerror, attempts in (('nt', 5, 5), ('nt', 32, 5), ('nt', 87, 1), ('posix', 5, 1)):
            with self.subTest(platform=platform, winerror=winerror), TemporaryDirectory() as root:
                path = Path(root) / 'state.json'
                atomic_json(path, {'pending': True})
                previous = path.read_bytes()
                error = PermissionError('synthetic denied replacement')
                error.winerror = winerror
                replace = Mock(side_effect=error)
                with patch.object(run_session, 'os', SimpleNamespace(name=platform, replace=replace)), \
                     patch.object(run_session._time, 'sleep'), self.assertRaises(PermissionError):
                    atomic_json(path, {'pending': False})
                self.assertEqual(replace.call_count, attempts)
                self.assertEqual(path.read_bytes(), previous)
                self.assertEqual(list(path.parent.iterdir()), [path])

    def test_serialization_failure_preserves_old_record(self):
        with TemporaryDirectory() as root:
            path = Path(root) / 'state.json'
            atomic_json(path, {'pending': True})
            previous = path.read_bytes()
            with self.assertRaises(TypeError):
                atomic_json(path, {'pending': object()})
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(list(path.parent.iterdir()), [path])
