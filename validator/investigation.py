"""Agent-directed, bounded retrieval over frozen Git objects."""
import json
from pathlib import PurePosixPath
import subprocess
import time

from .agent import invoke, validate_review
from .git import git
from .project import relative, ownership, investigation_settings
from .workflows import fields, require


def retrieve(build, context, request, deadline):
    fields(request, {'kind', 'path', 'query', 'snapshot', 'start_line', 'end_line'}, {'kind', 'path', 'query', 'snapshot'})
    kind, path, query, snapshot = (request[k] for k in ('kind', 'path', 'query', 'snapshot'))
    require(snapshot in ('target', 'baseline'), 'Invalid snapshot')
    sha = build[snapshot + '_sha']
    require(bool(sha), 'Snapshot unavailable')
    prefix = context.get('unity_project_prefix', '')
    require(isinstance(path, str) and isinstance(query, str), 'Invalid retrieval strings')
    result = dict(kind=kind, snapshot=snapshot, sha=sha)
    if kind in ('read', 'graph', 'find', 'read_lines'):
        settings = path.startswith(prefix+'ProjectSettings/') and kind != 'graph'
        require(relative(path) and (settings or path.startswith((prefix+'Assets/', prefix+'Packages/'))),
                'Path must be inside the configured Assets/Packages/ProjectSettings roots')
        extensions = {'.asset', '.txt', '.xml'} if settings else {
            '.cs', '.meta', '.prefab', '.unity', '.asset', '.controller',
            '.shadergraph', '.shader', '.asmdef', '.xml'}
        require(PurePosixPath(path).suffix.lower() in extensions, 'Unsupported source format')
    if kind in ('read', 'find', 'read_lines'):
        entry = git(build['repo'], 'ls-tree', '-z', sha, '--', ':(literal)'+path,
                    max_bytes=4096, deadline=deadline)
        require(bool(entry), f'File not present in {snapshot} snapshot {sha}: {path}. '
                'This does not establish whether it is generated during build; no working-tree fallback.')
        require(entry.startswith((b'100644 blob ', b'100755 blob ')), 'Source must be a regular committed file')
    if kind in ('find', 'read_lines'):
        from .source_windows import windows
        result.update(windows(build['repo'], sha, path, kind, query,
                              request.get('start_line'), request.get('end_line'), deadline))
    elif kind == 'read':
        raw = git(build['repo'], 'show', sha + ':' + path, max_bytes=75000, deadline=deadline)
        source = raw.decode('utf-8-sig')
        require('\0' not in source, 'Binary source rejected')
        result.update(path=path, source=source)
    elif kind == 'search':
        require(0 < len(query) <= 160 and query.strip() and not any(c in query for c in '\r\n\0'),
                'Search requires a nonempty single-line literal of at most 160 characters')
        try:
            raw = git(build['repo'], 'grep', '-l', '-z', '-I', '-F', '-e', query, sha, '--',
                      prefix+'Assets/*.cs', prefix+'Packages/*.cs', max_bytes=16000, truncate=True, deadline=deadline)
        except ValueError as exc:
            if str(exc):
                raise
            raw = b''
        paths = [r.decode('utf-8')[len(sha)+1:] for r in raw[:16000].split(b'\0')[:-1]
                 if r.startswith((sha+':').encode())]
        result.update(paths=paths[:40], truncated=len(raw)>16000 or len(paths)>40)
    elif kind == 'graph':
        require(path.endswith('.cs'), 'Graph request requires a C# script')
        options = context.get('investigation_graph')
        require(isinstance(options, dict), 'UnityGraph unavailable; enable --unity-project')
        from .unity_mcp import collect
        graph_build = {**build, 'target_sha': sha, 'baseline_sha': None}
        graph = collect(graph_build, [path], prefix, options['cache'], options['roots'],
                        min(deadline, time.monotonic()+20))
        result['graph'] = graph
        result['truncated'] = graph['status'] != 'COMPLETED' or bool(graph['limitations'])
    else:
        raise ValueError('Unknown retrieval kind')
    return result


def investigate(check, build, context, command, timeout, deadline):
    from .runner import unknown, run_check
    context = {**context, 'files': dict(context['files']), 'limitations': list(context['limitations']),
               'baseline_files': {}, 'tool_results': [], 'source_excerpts': {}, 'baseline_excerpts': {}}
    audit = {'rounds': [], 'findings': []}
    seen = set()
    remaining_bytes = 300000
    failures = []
    final = None
    try:
        settings = investigation_settings((context.get('project_config') or {}).get('investigation'))
        reserve = min(settings['verify_reserve_seconds'], max(0, deadline-time.monotonic())/3)
        investigation_deadline = deadline-reserve
        max_rounds = settings['max_rounds']
        audit.update(max_rounds=max_rounds, verify_reserve_seconds=reserve,
                     stop_reason='error', requested_verify_reserve_seconds=settings['verify_reserve_seconds'])
        for turn in range(1, max_rounds+1):
            remaining = investigation_deadline-time.monotonic()
            if remaining <= 0:
                audit['stop_reason'] = 'investigation_budget'
                raise subprocess.TimeoutExpired('investigation budget', 0)
            request = dict(phase='investigate', round=turn, max_rounds=max_rounds, remaining_seconds=remaining, check=check,
                           build={k: build[k] for k in ('build_id','repo','branch','profile','baseline_sha','target_sha')},
                           context=context, history=list(audit['rounds']))
            from .backends import response_schema
            request['output_schema'] = response_schema(request)
            try:
                response = invoke(command, request, min(timeout, remaining))
            except subprocess.TimeoutExpired:
                audit['stop_reason'] = 'investigation_budget' if time.monotonic() >= investigation_deadline else 'agent_timeout'
                raise
            fields(response, {'action','requests','findings','status','summary','evidence','limitations'},
                   {'action','requests','findings','status','summary','evidence','limitations'})
            require(response['action'] in ('retrieve','finish'), 'Invalid investigation action')
            require(isinstance(response['requests'], list) and len(response['requests']) <= 3, 'At most three retrieval requests')
            require(isinstance(response['findings'], list) and len(response['findings']) <= 5, 'At most five findings')
            # Validate the envelope as a normal review, including target evidence.
            envelope = validate_review({**response, 'check_id': check['id']}, check, build, context)
            audit['rounds'].append(response)
            if response['action'] == 'finish':
                audit['stop_reason'] = 'final_round_finished' if turn == max_rounds else 'agent_finished'
                require(not response['requests'], 'Finish cannot request tools')
                require((response['status'] == 'FAIL') == bool(response['findings']), 'FAIL requires findings; other statuses cannot include them')
                final = envelope
                candidates = [validate_review(f, check, build, context) for f in response['findings']]
                require(all(c['status'] == 'FAIL' for c in candidates), 'Findings must be FAIL candidates')
                for candidate in candidates:
                    verified = run_check({**check, 'executor': 'agent'}, build, context, command,
                                         timeout, deadline, initial_review=candidate)
                    verified['source_ownership'] = [{'file': e['file'], 'ownership': ownership(e['file'], context.get('project_config'))}
                                                    for e in candidate['evidence']]
                    audit['findings'].append(verified)
                break
            require(response['status'] == 'UNKNOWN' and not response['findings'] and response['requests'],
                    'Retrieve must be UNKNOWN with requests and no findings')
            if turn == max_rounds:
                audit['stop_reason'] = 'round_limit'
                failures.append('Investigation round limit reached before final assessment.')
                break
            for tool_request in response['requests']:
                try:
                    key = json.dumps(tool_request, sort_keys=True)
                    require(key not in seen, 'Repeated retrieval request rejected')
                    seen.add(key)
                    output = retrieve(build, context, tool_request, investigation_deadline)
                    if output['kind'] == 'read':
                        size = len(output['source'].encode('utf-8'))
                        require(size <= remaining_bytes, 'Additional source budget exhausted')
                        remaining_bytes -= size
                        bucket = 'files' if output['snapshot'] == 'target' else 'baseline_files'
                        context[bucket][output['path']] = output.pop('source')
                    elif output['kind'] in ('find', 'read_lines'):
                        size = sum(len(e['source'].encode('utf-8')) for e in output['excerpts'])
                        require(size <= remaining_bytes, 'Additional source budget exhausted')
                        remaining_bytes -= size
                        bucket = 'source_excerpts' if output['snapshot'] == 'target' else 'baseline_excerpts'
                        context[bucket].setdefault(output['path'], []).extend(output.pop('excerpts'))
                    if output.get('truncated'):
                        failures.append('Retrieval incomplete: ' + key)
                except (ValueError, OSError, TypeError, subprocess.TimeoutExpired) as exc:
                    output = {'error': str(exc), 'request': tool_request}
                    failures.append(str(exc))
                context['tool_results'].append(output)
        if final is None:
            result = unknown(check, 'Investigation ended without a final assessment.', 'COMPLETED')
        else:
            result = {**final, 'severity': check['severity'], 'execution_status':'COMPLETED', 'verified':False}
            confirmed = [f for f in audit['findings'] if f['status']=='FAIL' and f['verified']]
            if confirmed:
                result.update(status='FAIL', verified=True, summary=f'{len(confirmed)} independently confirmed finding(s).',
                              evidence=[e for f in confirmed for e in f['evidence']])
            elif audit['findings']:
                result.update(status='UNKNOWN', summary='No proposed finding was independently confirmed.')
            elif failures and result['status'] in ('PASS', 'NOT_APPLICABLE'):
                result.update(status='UNKNOWN', summary='Investigation has unresolved retrieval limitations. ' + result['summary'])
    except (ValueError, OSError, TypeError, subprocess.TimeoutExpired) as exc:
        if not isinstance(exc, subprocess.TimeoutExpired):
            audit['stop_reason'] = 'error'
        result = unknown(check, str(exc), 'TIMEOUT' if isinstance(exc, subprocess.TimeoutExpired) else 'ERROR')
    result['limitations'] += failures
    result['review_outcome'] = ('CONFIRMED_FINDINGS' if result['status'] == 'FAIL' and result['verified']
                               else 'NO_FINDINGS_IN_REVIEWED_SCOPE' if result['status'] == 'PASS'
                               else 'NOT_APPLICABLE' if result['status'] == 'NOT_APPLICABLE' else 'UNRESOLVED')
    supplied = set(context['files']) | set(context['source_excerpts'])
    result['coverage'] = {'supplied_target_paths': sorted(supplied),
                          'excerpt_only_paths': sorted(set(context['source_excerpts'])-set(context['files'])),
                          'changed_paths_without_source': sorted(set(context.get('changed_files', []))-supplied),
                          'limitations': list(dict.fromkeys(context['limitations']+result['limitations'])),
                          'note': 'Supplied source is not proof of exhaustive review or runtime execution.'}
    result['investigation'] = audit
    result['investigation_context'] = context
    return result
