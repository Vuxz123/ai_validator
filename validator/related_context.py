"""Read a bounded graph neighborhood, bound to a recorded commit and graph hash."""
import hashlib
import json
from pathlib import Path


def get_related_context(graph_path, manifest_path, expected_sha, script_path, max_edges=100):
    path = Path(graph_path)
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Graph exceeds 128 MiB')
    raw = path.read_bytes()
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if manifest['sha'] != expected_sha or manifest['graph_sha256'] != hashlib.sha256(raw).hexdigest():
        raise ValueError('Graph snapshot SHA or content hash mismatch')
    graph = json.loads(raw)
    nodes = {n['id']: n for n in graph['nodes']}
    seeds = {n['id'] for n in graph['nodes']
             if n.get('file_path', '').replace('\\', '/') == script_path.replace('\\', '/')}
    related = [e for e in graph['edges'] if e['from'] in seeds or e['to'] in seeds]
    # Preserve incoming/outgoing direction. Limit co-location noise after direct references.
    related.sort(key=lambda e: (e['type'] == 'co_exists_with', e['type'], e['from'], e['to']))
    chosen = related[:max_edges]
    ids = seeds | {e[k] for e in chosen for k in ('from', 'to')}
    return {'sha': expected_sha, 'script': script_path, 'seed_ids': sorted(seeds),
            'nodes': [nodes[i] for i in sorted(ids) if i in nodes], 'edges': chosen,
            'total_direct_edges': len(related), 'truncated': len(chosen) < len(related),
            'limitations': ['Direct neighborhood only; graph relationships are not proof of a bug.',
                            'Snapshot exports only supported text assets; no Unity import or runtime validation.']}
