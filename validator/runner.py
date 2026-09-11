"""Fixed analysis pipeline: collect, select, review, verify, report."""

import hashlib
import json
import subprocess
import time

from .agent import invoke, load_command, validate_review, validate_verification
from .git import context_for
from .workflows import load_workflows
from .project import load_config, route, ownership, project_prefix as config_prefix


def unknown(check, summary, execution='SKIPPED'):
    return {'check_id': check['id'], 'severity': check['severity'], 'status': 'UNKNOWN',
            'execution_status': execution, 'summary': summary, 'evidence': [],
            'limitations': [summary], 'verified': False}


def run_check(check, build, context, command, timeout, deadline, initial_review=None):
    if check['executor'] == 'git_snapshot':
        return {'check_id': check['id'], 'severity': check['severity'], 'status': 'PASS',
                'execution_status': 'COMPLETED', 'summary': 'Frozen Git trees read successfully.',
                'evidence': [], 'limitations': [], 'verified': False}
    if not command:
        return unknown(check, 'No agent configured.')
    if check['executor'] == 'investigation':
        from .investigation import investigate
        return investigate(check, build, context, command, timeout, deadline)
    if not context['files'] and not context.get('source_excerpts'):
        return unknown(check, 'No changed target text available for evidence.')
    request = {'phase': 'review', 'build': {k: build[k] for k in
               ('build_id', 'repo', 'branch', 'profile', 'baseline_sha', 'target_sha')},
               'check': check, 'context': context}
    result = None

    def call(payload):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired('analysis budget', 0)
        return invoke(command, payload, min(timeout, remaining))

    try:
        result = validate_review(initial_review if initial_review is not None else call(request), check, build, context)
        result.update(severity=check['severity'], execution_status='COMPLETED', verified=False)
        if result['status'] == 'UNKNOWN':
            from .review_context import collect as expand_review
            initial = dict(result)
            extra = expand_review(build, initial, context, deadline)
            audit = {'initial_review': initial, 'retrieval': extra, 'attempted': False}
            result['review_retry'] = audit
            if extra['new_files']:
                context = {**context, 'files': {**context['files'], **extra['files']},
                           'review_retrieval': {k: v for k, v in extra.items() if k != 'files'},
                           'limitations': context['limitations'] + extra['limitations']}
                request = {**request, 'context': context, 'review_attempt': 2,
                           'previous_review': initial}
                audit['attempted'] = True
                retried = validate_review(call(request), check, build, context)
                retried.update(severity=check['severity'], execution_status='COMPLETED',
                               verified=False, review_retry=audit)
                result = retried
        if result['status'] == 'FAIL':
            from .verification_context import collect
            extra = collect(build, result, deadline)
            result['verification_context'] = extra
            verification_context = {**context, 'files': {**context['files'], **extra['files']},
                                    'verification_retrieval': {k: v for k, v in extra.items() if k != 'files'},
                                    'limitations': context['limitations'] + extra['limitations']}
            verification = validate_verification(
                call({**request, 'phase': 'verify', 'finding': {
                    k: v for k, v in result.items() if k not in ('verification_context', 'review_retry')},
                    'context': verification_context}), build, verification_context)
            if verification['verdict'] == 'CONFIRMED':
                cited = {e['file'] for e in verification['evidence']}
                callers = set(extra['caller_files'])
                if not extra['complete'] or (callers and not cited.intersection(callers)):
                    verification['model_verdict'] = 'CONFIRMED'
                    verification['verdict'] = 'INCONCLUSIVE'
                    verification['summary'] = 'Verification lacks complete caller context or caller evidence. ' + verification['summary']
            result['verification'] = verification
            result['verified'] = verification['verdict'] == 'CONFIRMED'
            if not result['verified']:
                result['candidate'] = {'summary': result['summary'], 'evidence': result['evidence']}
                result['status'] = 'UNKNOWN'
                result['summary'] = 'Finding was not confirmed: ' + verification['summary']
        return result
    except subprocess.TimeoutExpired:
        fallback = unknown(check, 'Agent call or total analysis budget timed out.', 'TIMEOUT')
    except (ValueError, OSError, TypeError) as exc:
        fallback = unknown(check, str(exc), 'ERROR')
    if result is not None:
        fallback['candidate'] = result
    return fallback


def analyze(store, build_id, workflows, agent_command=None, timeout=60, budget=300, retry=False,
            backend=None, model=None, agent_executable=None,
            unity_project=None, graph_timeout=120, graph_root=None, project_config=None,
            fixture_execution=None):
    if fixture_execution is not None:
        from .workflows import fields, require
        fields(fixture_execution, {'entrypoint', 'assumption'}, {'entrypoint', 'assumption'})
        require(all(isinstance(v, str) and v.strip() and len(v) <= 2000
                    for v in fixture_execution.values()), 'Invalid fixture execution')
    if not 0 < timeout <= 600 or not 0 < budget <= 3600:
        raise ValueError('timeout must be (0,600], budget must be (0,3600] seconds')
    if backend and agent_command:
        raise ValueError('Choose --backend or --agent-command, not both')
    if (model or agent_executable) and not backend:
        raise ValueError('--model/--agent-executable requires --backend')
    if not 0 < graph_timeout <= 600:
        raise ValueError('graph-timeout must be (0,600] seconds')
    store.claim(build_id, retry)
    try:
        build = store.get(build_id)
        definitions = load_workflows(workflows)
        config = load_config(project_config)
        route(definitions, [], config)  # Validate enabled pack IDs even without a baseline.
        command = load_command(agent_command)
        if backend:
            from .backends import Backend
            command = Backend(backend, model, executable=agent_executable)
        report = {'schema_version': 1, 'build_id': build_id,
                  'baseline_sha': build['baseline_sha'], 'target_sha': build['target_sha'],
                  'advisory_only': True, 'checks': [], 'selected_workflows': [],
                  'workflow_definitions': definitions,
                  'workflow_hash': hashlib.sha256(json.dumps(definitions, sort_keys=True).encode()).hexdigest(),
                  'agent_configured': command is not None,
                  'backend': backend or ('custom' if command else None),
                  'requested_model': model,
                  'limitations': [], 'changed_files': []}
        report.update(project_config=config, routing_mode='project' if config is not None else 'legacy',
                      project_config_hash=hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest())
        report['assessment_scope'] = 'synthetic_fixture' if fixture_execution is not None else 'project'
        if not build['baseline_sha']:
            report.update(assessment='NO_BASELINE',
                          limitations=['Confirm a successful build to establish this branch/profile baseline.'])
        else:
            deadline = time.monotonic() + budget
            context = context_for(build, deadline=deadline)
            if fixture_execution is not None:
                context['fixture_execution'] = dict(fixture_execution)
                context['limitations'].append('Synthetic execution assumption supplied by evaluation harness; not proven project runtime reachability.')
            prefix = config_prefix(config) if config is not None else ''
            if unity_project:
                from . import unity_mcp
                from .unity_snapshot import project_prefix
                graph_prefix = project_prefix(build['repo'], unity_project)
                if config is not None and graph_prefix != prefix:
                    raise ValueError('--unity-project conflicts with project config unity_root')
                prefix = graph_prefix
                graph = unity_mcp.collect(build, context['changed_files'], prefix,
                                          store.path.parent / 'unitygraph-cache', graph_root or ['Assets', 'Packages'],
                                          min(deadline, time.monotonic() + min(graph_timeout, budget / 2)))
                context['unitygraph'] = graph
                context['limitations'] = [item for item in context['limitations'] if item not in (
                    'Graph/caller retrieval is not implemented; selection uses paths only.',
                    'Context contains changed text files only; unchanged dependencies are not included.')]
                context['limitations'].extend(graph['limitations'])
                graph_paths = [prefix + p for snapshot in graph.get('snapshots', {}).values()
                               for p in snapshot.get('related_paths', [])]
                try:
                    related = unity_mcp.text_context(build['repo'], prefix, build['target_sha'],
                                                    context['changed_files'], deadline, graph_paths)
                    context['caller_search'] = {k: v for k, v in related.items() if k != 'files'}
                    context['files'].update(related['files'])
                    context['limitations'].extend(related['limitations'])
                except Exception as exc:
                    graph['status'] = 'ERROR'
                    context['limitations'].append('Related target source retrieval failed: ' + str(exc))
                report['unity_project_prefix'] = prefix
            routing = route(definitions, context['changed_files'], config, prefix)
            selected_ids = {r['workflow_id'] for r in routing if r['status'] == 'SELECTED'}
            selected = [w for w in definitions if w['id'] in selected_ids]
            context['project_config'] = config
            context['unity_project_prefix'] = prefix
            if unity_project:
                context['investigation_graph'] = {'cache': str(store.path.parent / 'unitygraph-cache'),
                                                   'roots': graph_root or ['Assets', 'Packages']}
            for row in routing:
                if row['status'] == 'MISSING_MAPPING':
                    context['limitations'].append('Missing mapping for ' + row['workflow_id'] + ': ' + ', '.join(row['missing_groups']))
            report['routing'] = routing
            report['unity_project_prefix'] = prefix
            report.update(context=context, changed_files=context['changed_files'],
                          limitations=context['limitations'],
                          selected_workflows=[w['id'] for w in selected])
            from . import textures
            texture_data = None
            for workflow in selected:
                for check in workflow['checks']:
                    if check['executor'] in textures.EXECUTORS:
                        if texture_data is None:
                            texture_data = textures.collect(build, context['changed_files'], deadline, prefix)
                        result = textures.run(check, build, texture_data)
                    else:
                        result = run_check(check, build, context, command, timeout, deadline)
                    result['workflow_id'] = workflow['id']
                    result['source_ownership'] = [{'file': path, 'ownership': ownership(path, config)}
                        for path in sorted({e['file'] for e in result.get('evidence', [])})]
                    report['checks'].append(result)
            if any(c['status'] == 'FAIL' and (c['verified'] or c.get('deterministic')) for c in report['checks']):
                report['assessment'] = 'FINDINGS'
            elif (any(c['status'] == 'UNKNOWN' for c in report['checks'])
                  or any(r['status'] == 'MISSING_MAPPING' for r in routing)
                  or context.get('unitygraph', {}).get('status') == 'ERROR'):
                report['assessment'] = 'INCOMPLETE'
            else:
                report['assessment'] = 'NO_FINDINGS_IN_SELECTED_CHECKS'
        store.finish(build_id, report=report)
    except Exception as exc:
        store.finish(build_id, error=str(exc))
        raise
    return store.get(build_id)
