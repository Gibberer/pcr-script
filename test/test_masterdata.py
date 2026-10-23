"""Synthetic CDN, schema and publication regressions; no client/account data."""
from contextlib import closing
from hashlib import md5
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from pcrscript import masterdata as data


RULES = {'unit_profile': {'table': 'hashed_table', 'columns': {
    'unit_id': {'hash': 'hashed_id', 'type': 'INTEGER'},
    'unit_name': {'hash': 'hashed_name', 'type': 'TEXT'}}}}
BASE = 'https://l1-prod-patch-gzlj.bilibiligame.net/client_ob_771/'


class Response:
    status_code = 200
    def __init__(self, value):
        self.value = value
    def raise_for_status(self):
        pass
    def json(self):
        return self.value
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, size):
        yield self.value[:3]
        yield self.value[3:]


class MasterDataTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root/'catalogue.db'
        raw = self.root/'synthetic.mdb'
        with closing(sqlite3.connect(raw)) as conn:
            # Reordered fields and an added unknown field must not shift identity.
            conn.execute('CREATE TABLE hashed_table (extra TEXT,hashed_name TEXT,hashed_id INTEGER)')
            conn.execute('INSERT INTO hashed_table VALUES (?,?,?)', ('ignored', '合成角色', 100101))
            conn.commit()
        self.raw = raw.read_bytes()
        self.bundle = b'synthetic compressed resource'
        self.http = Mock()
        self.version = '202610231200'
        self.http.post.side_effect = lambda *a, **kw: Response(dict(
            data_headers=dict(result_code=1), data=dict(manifest_ver=self.version, resource=[BASE])))
        def get(url, **kw):
            if url.endswith('masterdata_assetmanifest_s'):
                body = f'a/masterdata_master.unity3d,0123456789abcdef,group,{len(self.bundle)},'.encode()
            elif url.endswith('masterdata_assetmanifest'):
                body = f'a/masterdata_master.unity3d,{md5(self.bundle).hexdigest()},unused,group,{len(self.bundle)},'.encode()
            else:
                body = self.bundle
            return Response(body)
        self.http.get.side_effect = get
        self.rules = patch.object(data, 'schema', return_value=RULES)
        self.rules.start()
        self.addCleanup(self.rules.stop)
        extract = patch.object(data, 'extract_database', return_value=self.raw)
        self.extract = extract.start()
        self.addCleanup(extract.stop)

    def update(self, **kwargs):
        return data.ensure_masterdata(self.target, http=self.http, **kwargs)

    def test_cold_update_has_named_fields_source_and_closed_handles(self):
        result = self.update()
        self.assertEqual(result['provider'], 'game_cdn')
        self.assertEqual(result['version'], self.version)
        self.assertFalse(result['cache_hit'])
        with closing(sqlite3.connect(self.target)) as conn:
            self.assertEqual(conn.execute('SELECT unit_id,unit_name FROM unit_profile').fetchall(),
                             [(100101, '合成角色')])
        # Windows replacement verifies that both source and candidate handles closed.
        alternate = self.root/'moved.db'
        self.target.replace(alternate)
        self.assertFalse(any(p.name.startswith('.masterdata-') for p in self.root.iterdir()))
        for call in self.http.post.call_args_list:
            self.assertNotIn('account', str(call))
            self.assertIn('timeout', call.kwargs)

    def test_nested_call_reuses_snapshot_without_network(self):
        self.update()
        self.http.reset_mock()
        result = self.update()
        self.assertTrue(result['cache_hit'])
        self.http.post.assert_not_called()
        self.http.get.assert_not_called()

    def test_force_checks_version_but_does_not_redownload_unchanged_master(self):
        self.update()
        self.http.reset_mock()
        self.update(force=True)
        self.http.post.assert_called_once()
        self.http.get.assert_not_called()

    def test_new_version_publishes_after_normalization(self):
        self.update()
        self.version = '202610241200'
        result = self.update(force=True)
        self.assertEqual(result['version'], self.version)
        self.assertEqual(data._metadata(self.target)['version'], self.version)

    def test_missing_file_is_downloaded_even_with_previous_source(self):
        self.update()
        self.target.unlink()
        self.http.reset_mock()
        self.assertFalse(self.update()['cache_hit'])
        self.http.get.assert_called()

    def test_network_failure_preserves_recent_verified_snapshot(self):
        self.update()
        original = self.target.read_bytes()
        self.http.post.side_effect = requests.ConnectionError('offline')
        value = self.update(force=True)
        self.assertTrue(value['stale'])
        self.assertEqual(self.target.read_bytes(), original)

    def test_network_failure_cannot_turn_legacy_or_expired_data_into_absence(self):
        self.target.write_bytes(b'legacy processed database')
        self.http.post.side_effect = requests.ConnectionError('offline')
        with self.assertRaises(data.MasterDataError):
            self.update()
        self.target.unlink()
        self.http.post.side_effect = lambda *a, **kw: Response(dict(
            data_headers=dict(result_code=1), data=dict(manifest_ver=self.version, resource=[BASE])))
        value = self.update()
        with patch.object(data.time, 'time', return_value=value['checked_at']+25*3600):
            self.http.post.side_effect = requests.ConnectionError('offline')
            with self.assertRaises(data.MasterDataError):
                self.update(max_age_hours=168)

    def test_offline_reads_only_recent_project_snapshot(self):
        with self.assertRaises(data.MasterDataError):
            self.update(offline=True)
        self.update()
        self.http.reset_mock()
        self.assertTrue(self.update(offline=True)['cache_hit'])
        self.http.post.assert_not_called()

    def test_unknown_schema_stops_even_when_old_snapshot_exists(self):
        self.update()
        original = self.target.read_bytes()
        self.version = '202610241200'
        broken = self.root/'broken.mdb'
        with closing(sqlite3.connect(broken)) as conn:
            conn.execute('CREATE TABLE hashed_table (hashed_id INTEGER, unknown TEXT)')
        self.extract.return_value = broken.read_bytes()
        with self.assertRaises(data.MasterDataSchemaError):
            self.update(force=True)
        self.assertEqual(self.target.read_bytes(), original)

    def test_changed_column_type_is_not_guessed(self):
        changed = json.loads(json.dumps(RULES))
        changed['unit_profile']['columns']['unit_id']['type'] = 'TEXT'
        with patch.object(data, 'schema', return_value=changed), self.assertRaises(data.MasterDataSchemaError):
            self.update()
        self.assertFalse(self.target.exists())

    def test_atomic_replace_failure_keeps_last_database(self):
        self.update()
        original = self.target.read_bytes()
        self.version = '202610241200'
        with patch.object(data.os, 'replace', side_effect=PermissionError('busy')):
            self.assertTrue(self.update(force=True)['stale'])
        self.assertEqual(self.target.read_bytes(), original)
        self.assertFalse(any(p.name.startswith('.masterdata-') for p in self.root.iterdir()))

    def test_corrupt_candidate_does_not_publish(self):
        self.extract.return_value = b'invalid SQLite'
        with self.assertRaises(data.MasterDataError):
            self.update()
        self.assertFalse(self.target.exists())

    def test_manifest_hash_size_and_download_limits_are_enforced(self):
        for body in (b'not manifest',
                     b'a/masterdata_master.unity3d,../bad,g,1,',
                     b'a/masterdata_master.unity3d,0123456789abcdef,g,9999999999,'):
            with self.subTest(body=body):
                self.http.get.side_effect = lambda *a, **kw: Response(body)
                with self.assertRaises(data.MasterDataError):
                    self.update()
        self.http.get.side_effect = lambda *a, **kw: Response(b'oversized')
        with self.assertRaises(data.MasterDataError):
            data._download(self.http, BASE, 3, 20, lambda: None)

    def test_md5_mismatch_rejects_bundle_before_extraction(self):
        good = self.http.get.side_effect
        self.http.get.side_effect = lambda url, **kw: (Response(
            b'a/masterdata_master.unity3d,00000000000000000000000000000000,unused,g,1,')
            if url.endswith('masterdata_assetmanifest') else good(url, **kw))
        with self.assertRaises(data.MasterDataError):
            self.update()
        self.extract.assert_not_called()

    def test_version_discovery_refuses_unknown_hosts_and_bad_versions(self):
        for base, version in [('https://example.com/', self.version), (BASE, '../version')]:
            with self.subTest(base=base, version=version):
                self.http.post.side_effect = lambda *a, **kw: Response(dict(
                    data_headers=dict(result_code=1), data=dict(manifest_ver=version, resource=[base])))
                with self.assertRaises(data.MasterDataError):
                    data.discover(self.http)

    def test_public_version_upgrade_does_not_require_client_installation(self):
        self.http.post.side_effect = [Response(dict(data_headers=dict(result_code=204, store_url='12.0.0'))),
                                        Response(dict(data_headers=dict(result_code=1),
                                                      data=dict(manifest_ver=self.version, resource=[BASE])))]
        version, _ = data.discover(self.http)
        self.assertEqual(version, self.version)
        self.assertEqual(self.http.post.call_args.kwargs['headers']['APP-VER'], '12.0.0')

    def test_cancellation_is_propagated_without_publishing(self):
        class Cancelled(BaseException):
            pass
        with self.assertRaises(Cancelled):
            self.update(check=Mock(side_effect=Cancelled))
        self.assertFalse(self.target.exists())


class BundleExtractionTests(TestCase):
    def test_only_unique_sqlite_text_asset_is_accepted(self):
        for values, succeeds in [([b'SQLite format 3\0synthetic'], True),
                                  ([b'other text'], False),
                                  ([b'SQLite format 3\0a', b'SQLite format 3\0b'], False)]:
            objects = []
            for value in values:
                obj = Mock()
                obj.type.name = 'TextAsset'
                obj.read.return_value.m_Script = value.decode('utf-8', errors='surrogateescape')
                objects.append(obj)
            with patch('UnityPy.load', return_value=Mock(objects=objects)):
                if succeeds:
                    self.assertEqual(data.extract_database(b'synthetic'), values[0])
                else:
                    with self.assertRaises(data.MasterDataError):
                        data.extract_database(b'synthetic')

    def test_parser_failure_is_a_format_error_for_fallback(self):
        import struct
        with patch('UnityPy.load', side_effect=struct.error('truncated')):
            with self.assertRaisesRegex(data.MasterDataError, 'error'):
                data.extract_database(b'synthetic')
