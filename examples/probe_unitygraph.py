"""Local UnityGraph feasibility probe from committed text assets, never working tree."""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from validator.related_context import get_related_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--target', default='HEAD')
    parser.add_argument('--script', default='Assets/BravestarsSDK/Scripts/NewSDK/AdController.cs')
    parser.add_argument('--include-root', action='append', help='Unity-relative asset directory; repeatable')
    args = parser.parse_args()
    include_roots = args.include_root or ['Assets/_Game', 'Assets/BravestarsSDK', 'Assets/ZeroX']
    project = Path(args.project).resolve()

    def git(*argv):
        return subprocess.check_output(['git', '-C', str(project), *argv], timeout=60)

    repo = Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve()
    prefix = project.relative_to(repo).as_posix()
    prefix = '' if prefix == '.' else prefix + '/'
    sha = git('rev-parse', '--verify', '--end-of-options', args.target + '^{commit}').decode().strip()
    listing = subprocess.check_output(['git', '-C', str(repo), 'ls-tree', '-r', '-l', '-z', sha], timeout=60)
    output_root = ROOT / '.validator/unitygraph-probes'
    output_root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=sha[:8] + '-', dir=output_root))
    snapshot = output / 'project'
    snapshot.mkdir()
    allowed = {'.cs', '.meta', '.unity', '.prefab', '.controller', '.shadergraph'}
    selected, omitted, total = [], [], 0
    def priority(entry):
        if not entry:
            return (9, b'')
        name = entry.split(b'\t', 1)[1].decode('utf-8')
        suffix = Path(name).suffix.lower()
        group = 0 if suffix in {'.cs', '.meta'} else 1 if suffix == '.unity' else 2
        return group, name

    for entry in sorted((e for e in listing.split(b'\0') if e), key=priority):
        if not entry:
            continue
        header, raw_path = entry.split(b'\t', 1)
        mode, kind, oid, size = header.decode().split()
        path = raw_path.decode('utf-8')
        if not path.startswith(prefix):
            continue
        relative = path[len(prefix):]
        if not any(relative.startswith(root.rstrip('/') + '/') for root in include_roots):
            continue
        if any('keystore' in part.lower() for part in Path(relative).parts):
            continue
        if not (relative.startswith('Assets/') and Path(relative).suffix.lower() in allowed):
            continue
        if kind != 'blob' or mode not in ('100644', '100755'):
            continue
        length = int(size)
        if length > 4 * 1024 * 1024 or total + length > 32 * 1024 * 1024:
            omitted.append(relative)
            continue
        destination = (snapshot / relative).resolve()
        if not destination.is_relative_to(snapshot):
            raise ValueError('Unsafe snapshot path')
        selected.append((oid, destination, relative, length))
        total += length
    print(f'Exporting {len(selected)} text assets ({total // 1024**2} MiB) at {sha}', flush=True)
    process = subprocess.Popen(['git', '-C', str(repo), 'cat-file', '--batch'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for oid, destination, relative, length in selected:
            process.stdin.write((oid + '\n').encode())
            process.stdin.flush()
            header = process.stdout.readline().decode().split()
            if len(header) != 3 or header[1] != 'blob' or int(header[2]) != length:
                raise ValueError('Unexpected Git object')
            data = process.stdout.read(length)
            if len(data) != length or process.stdout.read(1) != b'\n':
                raise ValueError('Incomplete Git object')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    finally:
        process.stdin.close()
        process.wait(timeout=10)
        process.stdout.close()
    from unitygraph.build.builder import build_project
    import unitygraph
    print('Building UnityGraph locally...', flush=True)
    result = build_project(snapshot)
    graph_path = output / 'graph.json'
    result.graph.write(graph_path)
    manifest = {'sha': sha, 'repo': str(repo), 'project_prefix': prefix,
                'unitygraph_version': unitygraph.__version__,
                'graph_sha256': hashlib.sha256(graph_path.read_bytes()).hexdigest(),
                'exported_files': len(selected), 'exported_bytes': total, 'omitted_by_budget': omitted,
                'include_roots': include_roots,
                'scope': 'Committed supported text assets only; signing paths and binary assets excluded.'}
    manifest_path = output / 'snapshot.json'
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (output / 'build-report.json').write_text(json.dumps(asdict(result.report), indent=2), encoding='utf-8')
    related = get_related_context(graph_path, manifest_path, sha, args.script)
    (output / 'related-context.json').write_text(json.dumps(related, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(output), 'sha': sha, 'nodes': len(result.graph.nodes),
                      'edges': len(result.graph.edges), 'build_ms': result.graph.build_ms,
                      'warnings': result.report.tallies(), 'omitted': len(omitted),
                      'seed_ids': related['seed_ids'], 'direct_edges': related['total_direct_edges'],
                      'edge_types': dict(Counter(e['type'] for e in related['edges']))}, indent=2))


if __name__ == '__main__':
    main()
