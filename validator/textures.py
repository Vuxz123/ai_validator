"""Deterministic checks on committed texture/meta pairs; never decode image data."""
from pathlib import PurePosixPath
import re
import subprocess

import yaml

from .git import git
from .workflows import unique_mapping


EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tga', '.psd', '.tif', '.tiff', '.bmp', '.exr', '.hdr', '.gif', '.iff', '.pict'}
EXECUTORS = {'texture_pairs', 'texture_guid', 'texture_importer'}


class MetaLoader(yaml.BaseLoader):
    """Keep numeric-looking GUIDs as strings, and reject duplicate mapping keys."""


MetaLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def parse_meta(text):
    if re.search(r'^(<<<<<<<|=======|>>>>>>>)(?:\s|$)', text, re.MULTILINE):
        raise ValueError('Unresolved merge conflict in metadata')
    value = yaml.load(text, Loader=MetaLoader)
    if not isinstance(value, dict):
        raise ValueError('Metadata must be a YAML mapping')
    return value


def collect(build, changed, deadline, prefix=''):
    paths = sorted({p[:-5] if p.endswith('.meta') else p for p in changed
                    if p.startswith(prefix + 'Assets/') and PurePosixPath(p[:-5] if p.endswith('.meta') else p).suffix.lower() in EXTENSIONS})
    data = {'assets': [], 'limitations': ['No global duplicate-GUID/reference scan or image/import execution.',
            'GUID stability compares the same path only; renamed assets are not matched by content.']}
    if len(paths) > 200:
        return {**data, 'error': 'More than 200 affected textures; narrow the build delta.'}
    try:
        trees = {}
        for sha in (build['baseline_sha'], build['target_sha']):
            entries = git(build['repo'], 'ls-tree', '-r', '-t', '-z', sha,
                          '--', prefix + 'Assets', deadline=deadline).decode('utf-8').split('\0')
            trees[sha] = {entry.split('\t', 1)[1]: entry.split('\t', 1)[0].split()[1]
                          for entry in entries if entry}
        for path in paths:
            target_kind = trees[build['target_sha']].get(path)
            baseline_kind = trees[build['baseline_sha']].get(path)
            if target_kind == 'tree' or (target_kind is None and baseline_kind == 'tree'):
                continue  # A folder can legitimately be named Icon.png and have its own .meta.
            item = {'path': path}
            for label, sha in [('baseline', build['baseline_sha']), ('target', build['target_sha'])]:
                item[label + '_asset'] = trees[sha].get(path) == 'blob'
                item[label + '_meta'] = trees[sha].get(path + '.meta') == 'blob'
                if item[label + '_meta']:
                    try:
                        item[label + '_text'] = git(build['repo'], 'show', f'{sha}:{path}.meta',
                                                  max_bytes=262144, deadline=deadline).decode('utf-8-sig')
                    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                        item[label + '_error'] = str(exc)
            data['assets'].append(item)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        data['error'] = str(exc)
    return data


def check_asset(executor, item):
    asset, metadata = item['target_asset'], item['target_meta']
    if executor == 'texture_pairs':
        if asset != metadata:
            return 'FAIL', 'Missing .meta file' if asset else 'Orphan .meta without texture'
        return 'PASS', 'Texture/meta pair present' if asset else 'Texture and .meta both removed'
    if not asset:
        return 'NOT_APPLICABLE', 'No texture at target path'
    if not metadata:
        return 'UNKNOWN', 'Cannot inspect missing .meta; see TEXTURE_META_001'
    if item.get('target_error'):
        return 'UNKNOWN', 'Cannot read target metadata: ' + item['target_error']
    try:
        target = parse_meta(item['target_text'])
    except (ValueError, yaml.YAMLError, RecursionError) as exc:
        return 'FAIL', 'Malformed target metadata: ' + str(exc)
    if executor == 'texture_importer':
        if not isinstance(target.get('TextureImporter'), dict):
            return 'FAIL', 'Missing or invalid TextureImporter mapping'
        return 'PASS', 'TextureImporter mapping present; project-specific settings not evaluated'
    guid = target.get('guid')
    if not isinstance(guid, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', guid) or guid == '0' * 32:
        return 'FAIL', 'GUID must be 32 hexadecimal characters and nonzero'
    if item['baseline_asset'] and item['baseline_meta']:
        if item.get('baseline_error'):
            return 'UNKNOWN', 'Cannot read baseline GUID'
        try:
            old = parse_meta(item['baseline_text']).get('guid')
        except (ValueError, yaml.YAMLError, RecursionError):
            return 'UNKNOWN', 'Cannot parse baseline GUID'
        if not isinstance(old, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', old) or old == '0' * 32:
            return 'UNKNOWN', 'Baseline GUID is invalid; cannot establish stability'
        if guid.lower() != old.lower():
            return 'FAIL', f'GUID changed at existing path: {old} -> {guid}'
    return 'PASS', 'GUID is valid and unchanged where a baseline pair exists'


def run(check, build, data):
    details = []
    for item in data['assets']:
        status, summary = check_asset(check['executor'], item)
        details.append({'path': item['path'], 'status': status, 'summary': summary})
    statuses = {d['status'] for d in details}
    status = ('FAIL' if 'FAIL' in statuses else 'UNKNOWN' if data.get('error') or 'UNKNOWN' in statuses
              else 'PASS' if 'PASS' in statuses else 'NOT_APPLICABLE')
    problems = [d for d in details if d['status'] in ('FAIL', 'UNKNOWN')]
    summary = f'{len(details)} texture path(s) checked; {len(problems)} issue(s).'
    if problems:
        summary += ' ' + '; '.join(f"{d['path']}: {d['summary']}" for d in problems[:3])
    if data.get('error'):
        summary += ' Incomplete scan: ' + data['error']
    return {'check_id': check['id'], 'severity': check['severity'], 'status': status,
            'summary': summary, 'verified': False, 'deterministic': True,
            'execution_status': 'ERROR' if data.get('error') else 'COMPLETED',
            'details': details, 'limitations': data['limitations'],
            'evidence': [{'kind': 'git_snapshot_comparison', 'file': d['path'] + '.meta',
                          'sha': build['target_sha'], 'baseline_sha': build['baseline_sha'],
                          'reason': d['summary']} for d in details]}
