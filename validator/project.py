"""Project mappings and explainable routing, independent of graph/model execution."""
from fnmatch import fnmatchcase
from pathlib import Path
import re

import yaml

from .workflows import UniqueLoader, fields, require, string_list


LEGACY_GROUPS = {'ads': ['Assets/Scripts/Ads/**', 'Assets/Scripts/Revive/**'],
                 'ui': ['Assets/Scripts/UI/**']}


def investigation_settings(value=None):
    value = {} if value is None else value
    fields(value, {'max_rounds', 'verify_reserve_seconds'}, set())
    rounds = value.get('max_rounds', 6)
    reserve = value.get('verify_reserve_seconds', 120)
    require(type(rounds) is int and 2 <= rounds <= 12, 'max_rounds must be 2..12')
    require(type(reserve) is int and 0 <= reserve <= 600, 'verify_reserve_seconds must be 0..600')
    return dict(max_rounds=rounds, verify_reserve_seconds=reserve)


def relative(value):
    return (isinstance(value, str) and bool(value) and not value.startswith('/')
            and '\\' not in value and ':' not in value
            and '..' not in value.split('/'))


def load_config(path):
    if path is None:
        return None
    path = Path(path)
    require(path.stat().st_size <= 100000, 'Project config too large')
    config = yaml.load(path.read_text(encoding='utf-8-sig'), Loader=UniqueLoader)
    fields(config, {'version', 'unity_root', 'source_groups', 'rule_packs', 'investigation'}, set())
    require(type(config.get('version', 1)) is int and config.get('version', 1) == 1,
            'Unsupported project config version')
    root = config.get('unity_root', '.')
    require(relative(root) and not any(c in root for c in '*?[]'), 'unity_root must be Git-relative')
    groups = config.get('source_groups', {})
    require(isinstance(groups, dict), 'source_groups must be a mapping')
    for name, patterns in groups.items():
        require(isinstance(name, str) and re.fullmatch(r'[a-z][a-z0-9_]*', name), 'Invalid source group')
        require(string_list(patterns) and all(relative(p) for p in patterns), 'Invalid source group patterns')
    packs = config.get('rule_packs')
    require(packs is None or (string_list(packs) and len(set(packs)) == len(packs)), 'Invalid rule_packs')
    return dict(version=1, unity_root=Path(root).as_posix().rstrip('/') or '.',
                source_groups=groups, rule_packs=packs,
                investigation=investigation_settings(config.get('investigation')))


def project_prefix(config):
    root = config['unity_root']
    return '' if root == '.' else root.rstrip('/') + '/'


def route(definitions, changed_paths, config=None, prefix=''):
    if config is not None:
        prefix = project_prefix(config)
    groups = config['source_groups'] if config is not None else LEGACY_GROUPS
    enabled = config.get('rule_packs') if config is not None else None
    if enabled is not None:
        require(not set(enabled) - {w['id'] for w in definitions}, 'Unknown rule pack ID')
    result = []
    for workflow in definitions:
        trigger = workflow['triggers']
        required = trigger.get('source_groups', [])
        missing = [name for name in required if name not in groups]
        patterns = trigger.get('changed_paths', []) + [p for name in required for p in groups.get(name, [])]
        matched = [p for p in changed_paths if p.startswith(prefix)
                   and any(fnmatchcase(p[len(prefix):], pattern) for pattern in patterns)]
        if enabled is not None and workflow['id'] not in enabled and workflow['id'] != 'common':
            status = 'DISABLED'
        elif missing:
            status = 'MISSING_MAPPING'
        elif trigger.get('always') or matched:
            status = 'SELECTED'
        else:
            status = 'NO_MATCH'
        result.append(dict(workflow_id=workflow['id'], version=workflow['version'], status=status,
                           matched_paths=matched, missing_groups=missing,
                           check_ids=[c['id'] for c in workflow['checks']]))
    return result


def ownership(path, config):
    if config is None:
        return 'unknown'
    prefix = project_prefix(config)
    if not path.startswith(prefix):
        return 'unknown'
    matches = [name for name in ('first_party', 'third_party')
               if any(fnmatchcase(path[len(prefix):], p) for p in config['source_groups'].get(name, []))]
    return matches[0] if len(matches) == 1 else ('mixed' if matches else 'unknown')
