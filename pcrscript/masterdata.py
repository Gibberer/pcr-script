"""Account-independent CN static data updates and project-owned schema adapters.

Only public resource metadata and CDN assets are requested. No device, root,
account session or downloaded executable participates in this module.
"""
from contextlib import closing
from hashlib import md5, sha256
import json
import os
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
import threading
import time
from urllib.parse import urlsplit

import requests


DATABASE = Path('cache/redive_cn.db')
SCHEMA = Path(__file__).with_name('data') / 'masterdata_schema.json'
VERSION_URL = 'https://l3-prod-all-gs-gzlj.bilibiligame.net/source_ini/get_maintenance_status?format=json'
RESOURCE_KEY = 'ab00a0a6dd915a052a2ef7fd649083e5'  # Public CN resource channel, not an account key.
_lock = threading.RLock()


class MasterDataError(RuntimeError):
    pass


class MasterDataSchemaError(MasterDataError):
    pass


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def schema():
    return json.loads(SCHEMA.read_text(encoding='utf-8'))['tables']


def _schema_digest():
    return sha256(SCHEMA.read_bytes()).hexdigest()


def _metadata(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        row = conn.execute('SELECT value FROM _pcrscript_metadata WHERE key=?', ('source',)).fetchone()
        value = json.loads(row[0])
        if value['schema'] != _schema_digest():
            raise MasterDataError('本地解析规则已变更，需要重新更新数据库')
        return value


def _resource_base(value):
    url = value if value.startswith('https://') else 'https://' + value
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port
            or not parsed.hostname or not re.fullmatch(r'l[0-9]+-prod-patch-gzlj\.bilibiligame\.net', parsed.hostname)
            or not re.fullmatch(r'/client_ob_[0-9]+/', parsed.path) or parsed.query or parsed.fragment):
        raise MasterDataError('资源版本接口返回了未知 CDN 地址')
    return url


def discover(http=requests, timeout=20):
    headers = {'APP-VER': '11.7.2', 'DEVICE': '2', 'RES-VER': '10002200',
               'RES-KEY': RESOURCE_KEY, 'SHORT-UDID': '0', 'LOCALE': 'CN', 'EXCEL-VER': '1.0.0'}
    for _ in range(2):
        response = http.post(VERSION_URL, data='{"viewer_id":"0"}', headers=headers, timeout=(10, timeout))
        response.raise_for_status()
        result = response.json()
        code = result.get('data_headers', {}).get('result_code')
        if code == 204:
            version = result['data_headers'].get('store_url', '')
            if isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+', version):
                headers['APP-VER'] = version
                continue
        if code != 1:
            raise MasterDataError(f'公开资源版本查询失败：{code}')
        data = result['data']
        version = str(data['manifest_ver'])
        if not re.fullmatch(r'\d{12}', version):
            raise MasterDataError('资源清单版本格式未知')
        bases = list(dict.fromkeys(_resource_base(x) for x in data['resource']))
        if not bases:
            raise MasterDataError('公开资源版本未提供 CDN')
        return version, bases
    raise MasterDataError('公开资源版本要求的客户端版本无法确认')


def _download(http, url, limit, timeout, check):
    # Bound both transfer size and pauses; redirects must stay on the exact CDN.
    with http.get(url, stream=True, timeout=(10, timeout), allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise MasterDataError('资源 CDN 未返回完整文件')
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            check()
            size += len(chunk)
            if size > limit:
                raise MasterDataError('静态数据下载超出大小边界')
            chunks.append(chunk)
        return b''.join(chunks)


def _master_bundle(http, version, base, timeout, check):
    url = f'{base}Manifest/AssetBundles/Android/{version}/manifest/masterdata_assetmanifest_s'
    manifest = _download(http, url, 65536, timeout, check).decode('utf-8')
    rows = [line.split(',') for line in manifest.splitlines() if line.strip()]
    entries = [r for r in rows if r[0] == 'a/masterdata_master.unity3d']
    if len(entries) != 1 or len(entries[0]) < 4:
        raise MasterDataError('主库资源清单格式未知或存在多个主库')
    _, digest, _, size, *_ = entries[0]
    if not re.fullmatch(r'[a-f0-9]{16}', digest) or not size.isdecimal() or not 0 < int(size) <= 100*1024**2:
        raise MasterDataError('主库资源清单哈希或大小异常')
    bundle_url = f'{base}pool/AssetBundles/Android/{digest[:2]}/{digest}'
    bundle = _download(http, bundle_url, int(size), timeout, check)
    if len(bundle) != int(size):
        raise MasterDataError('主库资源包下载不完整')
    legacy_url = url.removesuffix('_s')
    legacy = _download(http, legacy_url, 65536, timeout, check).decode('utf-8')
    hashes = [r.split(',')[1] for r in legacy.splitlines()
              if r.startswith('a/masterdata_master.unity3d,')]
    if len(hashes) != 1 or not re.fullmatch(r'[a-f0-9]{32}', hashes[0]) or md5(bundle).hexdigest() != hashes[0]:
        raise MasterDataError('主库资源包 MD5 与资源清单不一致')
    return bundle, bundle_url, digest


def extract_database(bundle):
    import UnityPy
    # The CN bundle omits its engine version; this format was verified against
    # the matching client master, including SHA-256 of the extracted SQLite.
    UnityPy.config.FALLBACK_UNITY_VERSION = '6000.0.58f2'
    values = []
    try:
        for obj in UnityPy.load(bundle).objects:
            if obj.type.name == 'TextAsset':
                value = obj.read().m_Script
                value = value.encode('utf-8', errors='surrogateescape') if isinstance(value, str) else bytes(value)
                if value.startswith(b'SQLite format 3\0'):
                    values.append(value)
    except Exception as error:
        # Parser failures are format errors; they must reach CDN and cache fallback.
        raise MasterDataError('资源包无法解析：'+type(error).__name__) from error
    if len(values) != 1 or len(values[0]) > 700*1024**2:
        raise MasterDataError('资源包中没有唯一且有效的 SQLite 主库')
    return values[0]


def normalize(raw, destination, source, *, tables=None, check=lambda: None):
    """Copy explicitly identified columns; never infer identities from row similarity.

    Additional client columns are allowed. Missing or changed known columns
    invalidate the candidate, preserving the previously validated database.
    """
    tables = schema() if tables is None else tables
    with closing(sqlite3.connect(Path(raw).resolve().as_uri()+'?mode=ro', uri=True)) as src, \
            closing(sqlite3.connect(destination)) as dst:
        if src.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise MasterDataError('客户端静态主库完整性检查失败')
        for name, rule in tables.items():
            check()
            actual = {r[1]: r[2].upper() for r in src.execute('PRAGMA table_info('+_quote(rule['table'])+')')}
            columns = rule['columns']
            if not columns or any(actual.get(c['hash']) != c['type'] for c in columns.values()):
                raise MasterDataSchemaError('静态主库结构无法确认：'+name)
            dst.execute('CREATE TABLE '+_quote(name)+' ('+', '.join(
                _quote(k)+' '+v['type'] for k, v in columns.items())+')')
            rows = src.execute('SELECT '+','.join(_quote(c['hash']) for c in columns.values())+
                               ' FROM '+_quote(rule['table']))
            while batch := rows.fetchmany(2000):
                check()
                dst.executemany('INSERT INTO '+_quote(name)+' VALUES ('+','.join('?' for _ in columns)+')', batch)
        dst.execute('CREATE TABLE _pcrscript_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        dst.execute('INSERT INTO _pcrscript_metadata VALUES (?,?)', ('source', json.dumps(source)))
        dst.commit()
        if dst.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise MasterDataError('转换后的静态数据库完整性检查失败')


def ensure_masterdata(path=DATABASE, *, http=requests, max_age_hours=6, timeout=30,
                      force=False, offline=False, check=lambda: None):
    """Refresh once per TTL for GUI, CLI and nested tasks, with atomic publication.

    Cached snapshots must carry this project's schema fingerprint. An update
    failure may use such a snapshot for at most 24 hours since last validation.
    Legacy third-party files never qualify as a verified fallback.
    """
    path = Path(path)
    with _lock:
        now = time.time()
        try:
            saved = _metadata(path)
            age = now - saved['checked_at']
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, MasterDataError):
            saved, age = {}, float('inf')
        if saved and not force and 0 <= age < min(max_age_hours, 24)*3600:
            return dict(saved, database=str(path), cache_hit=True, stale=False)
        if offline:
            if saved and 0 <= age <= 24*3600:
                return dict(saved, database=str(path), cache_hit=True, stale=True)
            raise MasterDataError('没有24小时内验证过的本地静态数据库')
        try:
            check()
            version, bases = discover(http, timeout)
            if saved and saved['version'] == version:
                saved = dict(saved, checked_at=now)
                with closing(sqlite3.connect(path)) as conn:
                    conn.execute('UPDATE _pcrscript_metadata SET value=? WHERE key=?', (json.dumps(saved), 'source'))
                    conn.commit()
                return dict(saved, database=str(path), cache_hit=True, stale=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix='.masterdata-', dir=path.parent) as temporary:
                last_error = None
                for base in bases:
                    try:
                        bundle, url, digest = _master_bundle(http, version, base, timeout, check)
                        raw_bytes = extract_database(bundle)
                        break
                    except (requests.RequestException, ValueError, MasterDataError) as error:
                        last_error = error
                else:
                    raise MasterDataError('所有游戏资源 CDN 均未提供有效主库') from last_error
                raw, candidate = Path(temporary)/'master.mdb', Path(temporary)/'catalogue.db'
                raw.write_bytes(raw_bytes)
                value = dict(provider='game_cdn', version=version, source=url, resource_hash=digest,
                             master_sha256=sha256(raw_bytes).hexdigest(), schema=_schema_digest(), checked_at=now)
                normalize(raw, candidate, value, check=check)
                # Connections are closed before replacing, including on Windows.
                os.replace(candidate, path)
            return dict(value, database=str(path), cache_hit=False, stale=False)
        except (requests.RequestException, OSError, ValueError, KeyError, TypeError, sqlite3.Error, MasterDataError) as error:
            if isinstance(error, MasterDataSchemaError):
                raise
            if not saved or not 0 <= age <= 24*3600:
                raise MasterDataError('无法更新任务前置数据库，未将未知信息视为玩法未开放：'+str(error)) from error
            return dict(saved, database=str(path), cache_hit=True, stale=True,
                        warning='静态数据库更新失败，使用24小时内已验证缓存：'+type(error).__name__)
