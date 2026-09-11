"""Optional UnityGraph stdio MCP retrieval, isolated from the build pipeline."""
import asyncio
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import time

from .git import git
from .unity_snapshot import safe_asset
from .unity_index import index_cache, neighborhood, file_hash

ROOT = Path(__file__).resolve().parents[1]
LIMITS = ['Graph edges and text matches are unverified retrieval hints, not proof of a bug.',
          'Singleton/dynamic callers may be missing; equal type names may resolve incorrectly.',
          'Index covers supported committed Assets/Packages text; no Unity import or runtime validation.']


def text_context(repo, prefix, sha, changed, deadline, extra_paths=()):
    """Search target Git text (including unchanged callers), never the worktree."""
    names = sorted({PurePosixPath(p).stem for p in changed if p.endswith('.cs')
                    and p.startswith((prefix + 'Assets/', prefix + 'Packages/'))
                    and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', PurePosixPath(p).stem)})[:8]
    matches, paths, limitations = [], list(extra_paths), []
    if names:
        # grep exit 1 means no matches; use an object-only file inventory instead
        # of the worktree, and handle that one expected return code explicitly.
        try:
            raw = git(repo, 'grep', '-n', '-I', '-E', '-e', r'\b(' + '|'.join(names) + r')\b',
                      sha, '--', prefix + 'Assets/*.cs', prefix + 'Packages/*.cs', max_bytes=32000, truncate=True, deadline=deadline)
        except ValueError as exc:
            if str(exc):
                raise
            raw = b''
        if len(raw) > 32000:
            limitations.append('Caller search truncated to 32 KiB.')
        for line in raw[:32000].decode('utf-8', errors='replace').splitlines():
            match = re.match(r'^[^:]+:(.+?):(\d+):(.*)$', line)
            if not match:
                continue
            path, number, snippet = match.groups()
            if not path.startswith(prefix) or not safe_asset(path[len(prefix):]):
                continue
            paths.append(path)
            if len(matches) < 60:
                matches.append({'file': path, 'line': int(number), 'snippet': snippet[:300]})
    files, remaining = {}, 60000
    paths = list(dict.fromkeys(paths))
    candidates = []
    for path in paths[:20]:
        if not path.startswith(prefix) or not safe_asset(path[len(prefix):]):
            continue
        if PurePosixPath(path).suffix.lower() not in {'.cs', '.prefab', '.unity', '.meta'}:
            continue
        try:
            size = int(git(repo, 'cat-file', '-s', f'{sha}:{path}', deadline=deadline))
            candidates.append((size, path))
        except ValueError:
            limitations.append('Related target source unavailable: ' + path)
    # Include smaller callers before large SDK/prefab files consume all bytes.
    for size, path in sorted(candidates):
        if size > remaining:
            limitations.append('Related source omitted due to budget: ' + path)
            continue
        try:
            data = git(repo, 'show', f'{sha}:{path}', max_bytes=max(1, remaining), deadline=deadline)
            text = data.decode('utf-8')
            if '\0' not in text:
                files[path] = text
                remaining -= len(data)
        except (ValueError, UnicodeDecodeError):
            limitations.append('Related source unavailable or over budget: ' + path)
    if len(paths) > 20 or len(names) == 8:
        limitations.append('Related source search is bounded to 8 names and 20 files.')
    return {'sha': sha, 'files': files, 'matches': matches, 'limitations': limitations}


async def query_mcp(graph, seeds):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    parameters = StdioServerParameters(command=sys.executable,
                                       args=['-m', 'unitygraph.serve', str(graph)])
    queries, paths, remaining = [], set(), 24000
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for seed in seeds[:8]:
                response = await session.call_tool('get_neighbors', {'node_id': seed['id'], 'hops': 1})
                if response.isError:
                    raise ValueError('UnityGraph MCP get_neighbors returned an error')
                value = response.structuredContent
                if value is None:
                    value = json.loads(''.join(c.text for c in response.content if c.type == 'text'))
                # Only node identity/location crosses into model context; large
                # Inspector payloads are omitted and source is fetched separately.
                nodes = []
                for node in value.get('neighbors', []):
                    compact = {k: node[k] for k in ('id', 'type', 'name', 'namespace', 'file_path', 'scope') if k in node}
                    size = len(json.dumps(compact).encode())
                    if size > remaining or len(nodes) >= 50:
                        break
                    remaining -= size
                    nodes.append(compact)
                    if node.get('file_path'):
                        paths.add(node['file_path'].replace('\\', '/'))
                    scope = node.get('scope', '')
                    match = re.search(r'((?:Assets|Packages)[\\/].+?\.(?:prefab|unity))(?:::|$)', scope)
                    if match:
                        paths.add(match[1].replace('\\', '/'))
                queries.append({'tool': 'get_neighbors', 'node_id': seed['id'],
                                'result': {'found': value.get('found', False), 'neighbors': nodes,
                                           'neighbor_count': value.get('neighbor_count', 0),
                                           'truncated': len(nodes) < value.get('neighbor_count', 0)}})
    return queries, sorted(paths)


def snapshot_query(request):
    database, manifest, reused = index_cache(request['repo'], request['prefix'], request['sha'],
                                             request['roots'], request['cache'])
    if request.get('index_only'):
        return {'status': 'COMPLETED', 'cache_hit': reused, 'manifest_path': str(database.parent / 'snapshot.json'),
                'manifest': manifest}
    paths = [p[len(request['prefix']):] for p in request['changed'] if p.startswith(request['prefix'])]
    data, index_truncated = neighborhood(database, paths)
    changed = set(request['changed'])
    seeds = [n for n in data['nodes'] if n.get('type') == 'Script'
             and request['prefix'] + n.get('file_path', '').replace('\\', '/') in changed]
    with tempfile.TemporaryDirectory(prefix='query-', dir=request['cache']) as directory:
        graph = Path(directory) / 'graph.json'
        graph.write_text(json.dumps(data), encoding='utf-8')
        query_hash = file_hash(graph)
        queries, paths = asyncio.run(query_mcp(graph, seeds))
    if file_hash(database) != manifest['index_sha256']:
        raise ValueError('Index content hash changed during MCP query')
    # Keep directed edges separate from the MCP's undirected neighborhood.
    ids = {s['id'] for s in seeds[:8]}
    edges = [e for e in data['edges'] if e['from'] in ids or e['to'] in ids]
    edges.sort(key=lambda e: (e['type'] == 'co_exists_with', e['type']))
    selected, remaining = [], 16000
    for edge in edges:
        item = {k: edge[k] for k in ('from', 'to', 'type')}
        item['sites'] = [{k: s[k] for k in ('file', 'line', 'kind') if k in s}
                         for s in edge.get('sites', [])[:3]]
        size = len(json.dumps(item).encode())
        if len(selected) >= 50 or size > remaining:
            break
        remaining -= size
        selected.append(item)
    return {'status': 'COMPLETED', 'sha': request['sha'], 'transport': 'mcp-stdio',
            'manifest_path': str(database.parent / 'snapshot.json'), 'cache_hit': reused,
            'graph_sha256': query_hash, 'index_sha256': manifest['index_sha256'], 'scope': manifest['include_roots'],
            'coverage': manifest['coverage'], 'indexed_files': manifest['exported_files'],
            'omitted_count': manifest['omitted_count'], 'warnings': manifest['warnings'],
            'queries': queries, 'edges': selected, 'related_paths': paths,
            'truncated': index_truncated or len(seeds) > 8 or len(selected) < len(edges),
            'limitations': LIMITS + manifest['limitations'] + (['No changed script seed found in graph.'] if not seeds else [])}


def collect(build, changed, prefix, cache, roots, deadline):
    from .backends import execute
    result = {'status': 'COMPLETED', 'snapshots': {}, 'files': {}, 'limitations': list(LIMITS)}
    if not any(p.startswith((prefix + 'Assets/', prefix + 'Packages/')) and p.endswith('.cs') for p in changed):
        result.update(status='SKIPPED', limitations=['MCP retrieval currently targets C# changes only.'])
        return result
    for label in ('target', 'baseline'):
        sha = build[label + '_sha']
        if not sha:
            continue
        request = {'repo': build['repo'], 'prefix': prefix, 'sha': sha,
                   'cache': str(Path(cache).resolve()), 'roots': roots, 'changed': changed}
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Graph retrieval budget exhausted')
            raw = execute([sys.executable, '-m', 'validator.unity_mcp'], ROOT,
                          json.dumps(request).encode(), os.environ.copy(), remaining)
            if len(raw) > 128000:
                raise ValueError('MCP worker response exceeds 128 KiB')
            snapshot = json.loads(raw)
            if snapshot.get('status') != 'COMPLETED':
                raise ValueError(snapshot.get('error', 'MCP worker failed'))
            result['snapshots'][label] = snapshot
            result['limitations'].extend(snapshot['limitations'])
            if snapshot['omitted_count'] or snapshot['warnings'] or snapshot['truncated']:
                result['limitations'].append(label + ': scoped graph has omissions, warnings or truncated context.')
        except Exception as exc:
            result['status'] = 'ERROR'
            result['limitations'].append(label + ': ' + str(exc)[:1000])
    result['limitations'] = list(dict.fromkeys(result['limitations']))
    return result


def prepare_index(repo, project, sha, cache, roots, timeout=1800):
    from .backends import execute
    from .unity_snapshot import project_prefix
    if not 0 < timeout <= 3600:
        raise ValueError('index-timeout must be (0,3600] seconds')
    request = {'repo': repo, 'prefix': project_prefix(repo, project), 'sha': sha,
               'cache': str(Path(cache).resolve()), 'roots': roots, 'index_only': True}
    raw = execute([sys.executable, '-m', 'validator.unity_mcp'], ROOT,
                  json.dumps(request).encode(), os.environ.copy(), timeout)
    return json.loads(raw)


if __name__ == '__main__':
    try:
        payload = json.load(sys.stdin)
        output = snapshot_query(payload)
    except Exception as exc:
        output = {'status': 'ERROR', 'error': str(exc)[:1000]}
    print(json.dumps(output, ensure_ascii=True))
