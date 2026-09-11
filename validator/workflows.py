"""Validate the small supported workflow vocabulary before invoking any agent."""

from pathlib import Path
import re

import yaml


DEFAULT_WORKFLOWS = Path(__file__).resolve().parents[1] / 'workflows'
PROVIDERS = {'changed_code', 'diff'}


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError(f'Duplicate or non-string YAML key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, allowed, required):
    require(isinstance(value, dict), 'Expected a mapping')
    require(not set(value) - set(allowed), f'Unknown fields: {set(value) - set(allowed)}')
    require(set(required) <= set(value), f'Missing required fields: {set(required) - set(value)}')


def string_list(value):
    return isinstance(value, list) and bool(value) and all(isinstance(x, str) and x for x in value)


def load_workflows(folder):
    paths = sorted(Path(folder).glob('*.yaml'))
    require(bool(paths), f'No .yaml workflows in {folder}')
    workflows, workflow_ids, check_ids = [], set(), set()
    for path in paths:
        require(path.stat().st_size <= 100000, f'Workflow too large: {path}')
        workflow = yaml.load(path.read_text(encoding='utf-8'), Loader=UniqueLoader)
        fields(workflow, {'id', 'version', 'triggers', 'checks'}, {'id', 'version', 'triggers', 'checks'})
        require(isinstance(workflow['id'], str) and re.fullmatch(r'[a-z][a-z0-9_]*', workflow['id']),
                'Invalid workflow id')
        require(workflow['id'] not in workflow_ids, 'Duplicate workflow id')
        require(type(workflow['version']) is int and workflow['version'] > 0, 'Invalid version')
        workflow_ids.add(workflow['id'])
        triggers = workflow['triggers']
        fields(triggers, {'always', 'changed_paths', 'source_groups'}, set())
        require(triggers.get('always') is True or string_list(triggers.get('changed_paths'))
                or string_list(triggers.get('source_groups')),
                'Specify always: true, changed_paths or source_groups')
        if 'source_groups' in triggers:
            require(string_list(triggers['source_groups']), 'source_groups must be a nonempty list')
        if 'always' in triggers:
            require(type(triggers['always']) is bool, 'always must be boolean')
        if 'changed_paths' in triggers:
            require(string_list(triggers['changed_paths']), 'changed_paths must be a list of strings')
        require(isinstance(workflow['checks'], list) and 0 < len(workflow['checks']) <= 50,
                'Workflow requires 1..50 checks')
        for check in workflow['checks']:
            fields(check, {'id', 'description', 'executor', 'severity', 'context', 'evidence_required',
                           'objective', 'instructions', 'context_requests', 'verdicts'},
                   {'id', 'executor', 'severity'})
            if 'objective' in check:
                require(isinstance(check['objective'], str) and check['objective'].strip(), 'Invalid objective')
                check.setdefault('description', check['objective'])
            for key in ('instructions', 'context_requests'):
                if key in check:
                    require(string_list(check[key]), key + ' must be a nonempty string list')
            if 'verdicts' in check:
                fields(check['verdicts'], {'pass', 'fail', 'unknown', 'not_applicable'}, {'pass', 'fail', 'unknown'})
                require(all(isinstance(v, str) and v.strip() for v in check['verdicts'].values()), 'Invalid verdict criteria')
            require(isinstance(check['id'], str) and re.fullmatch(r'[A-Z][A-Z0-9_]*', check['id']),
                    'Invalid check id')
            require(check['id'] not in check_ids, 'Duplicate check id')
            check_ids.add(check['id'])
            require(isinstance(check.get('description'), str) and check['description'].strip(),
                    'Missing description')
            require(check['executor'] in ('agent', 'investigation', 'git_snapshot', 'texture_pairs',
                                         'texture_guid', 'texture_importer'), 'Unknown executor')
            require(check['severity'] in ('low', 'medium', 'high', 'critical'), 'Unknown severity')
            if check['executor'] in ('agent', 'investigation'):
                if 'objective' in check:
                    check.setdefault('context', ['changed_code', 'diff'])
                require(string_list(check.get('context')), 'Agent check requires context')
                require(set(check['context']) <= PROVIDERS, 'Unsupported context provider')
                require(string_list(check.get('evidence_required')), 'Agent check requires evidence_required')
            else:
                require(not {'objective', 'instructions', 'context_requests', 'verdicts'} & set(check),
                        'AI guidance requires executor: agent')
        workflows.append(workflow)
    require(len(check_ids) <= 100, 'At most 100 checks supported')
    return workflows


def select_workflows(workflows, changed_paths):
    from .project import route
    selected = {r['workflow_id'] for r in route(workflows, changed_paths) if r['status'] == 'SELECTED'}
    return [w for w in workflows if w['id'] in selected]
