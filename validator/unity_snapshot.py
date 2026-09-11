"""Bounded committed Unity text snapshots and immutable local graph cache."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tempfile

from .git import git

SCHEMA = 1
MAX_GRAPH = 128 * 1024 * 1024
EXTENSIONS = {'.cs', '.meta', '.unity', '.prefab', '.controller', '.shadergraph'}


def safe_asset(path):
    parts = PurePosixPath(path).parts
    return (path.startswith(('Assets/', 'Packages/')) and '\\' not in path and ':' not in path
            and '..' not in parts and not any('keystore' in p.lower() for p in parts))


def project_prefix(repo, project):
    relative = Path(project).resolve().relative_to(Path(repo).resolve()).as_posix()
    return '' if relative == '.' else relative + '/'


def export_snapshot(repo, prefix, sha, destination, roots, full=False):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for root in roots:
        if not safe_asset(root.rstrip('/') + '/'):
            raise ValueError('Graph roots must be directories under Assets or Packages')
    entries = []
    unsupported = {}
    for entry in git(repo, 'ls-tree', '-r', '-l', '-z', sha, '--', prefix + 'Assets',
                     prefix + 'Packages', prefix + 'ProjectSettings/MonoManager.asset',
                     max_bytes=32 * 1024 * 1024).split(b'\0'):
        if not entry:
            continue
        header, raw = entry.split(b'\t', 1)
        mode, kind, oid, size = header.decode().split()
        path = raw.decode('utf-8')
        if not path.startswith(prefix):
            continue
        path = path[len(prefix):]
        suffix = PurePosixPath(path).suffix.lower()
        special = full and path in ('ProjectSettings/MonoManager.asset', 'Packages/manifest.json', 'Packages/packages-lock.json')
        if full and suffix not in EXTENSIONS and not special:
            unsupported[suffix] = unsupported.get(suffix, 0) + 1
        if (mode not in ('100644', '100755') or kind != 'blob' or not safe_asset(path)
                or suffix not in EXTENSIONS
                or not any(path.startswith(r.rstrip('/') + '/') for r in roots)):
            if not special or mode not in ('100644', '100755') or kind != 'blob':
                continue
        priority = 0 if suffix in {'.cs', '.meta'} else 1 if suffix == '.unity' else 2
        entries.append((priority, path, oid, int(size)))
    total, selected, omitted = 0, [], []
    for _, path, oid, size in sorted(entries):
        if full and (size > 64 * 1024 * 1024 or total + size > 2 * 1024**3):
            raise ValueError('Full index safety limit exceeded (64 MiB/file, 2 GiB export); no partial index published')
        if not full and (size > 4 * 1024 * 1024 or total + size > 32 * 1024 * 1024):
            omitted.append(path)
        else:
            selected.append((path, oid, size))
            total += size
    # The containing worker enforces an overall deadline and terminates this tree.
    process = subprocess.Popen(['git', '-C', repo, 'cat-file', '--batch'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        for path, oid, size in selected:
            process.stdin.write((oid + '\n').encode())
            process.stdin.flush()
            header = process.stdout.readline().decode().split()
            if len(header) != 3 or header[1] != 'blob' or int(header[2]) != size:
                raise ValueError('Unexpected Git batch object')
            data = process.stdout.read(size)
            if len(data) != size or process.stdout.read(1) != b'\n':
                raise ValueError('Incomplete Git batch object')
            target = (destination / path).resolve()
            if not target.is_relative_to(destination):
                raise ValueError('Unsafe export path')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    finally:
        process.stdin.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        process.stdout.close()
    return {'sha': sha, 'project_prefix': prefix, 'include_roots': roots,
            'exported_files': len(selected), 'exported_bytes': total,
            'omitted_count': len(omitted), 'omitted_sample': omitted[:100],
            'unsupported_extensions': unsupported,
            'coverage': 'all_supported_committed_text_in_selected_roots' if full else 'budgeted_text'}


def graph_cache(repo, prefix, sha, roots, cache):
    import unitygraph
    from unitygraph.build.builder import build_project
    identity = {'schema': SCHEMA, 'repo': str(Path(repo).resolve()), 'prefix': prefix,
                'sha': sha, 'roots': roots, 'version': unitygraph.__version__}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cache = Path(cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    final = cache / key
    reused = final.exists()
    if not reused:
        # Concurrent builds have separate staging paths. Only a complete directory
        # is published; an interrupted staging directory is never a cache hit.
        with tempfile.TemporaryDirectory(prefix='staging-', dir=cache) as staging:
            stage = Path(staging)
            manifest = export_snapshot(repo, prefix, sha, stage / 'project', roots)
            result = build_project(stage / 'project')
            publish = stage / 'publish'
            publish.mkdir()
            graph = publish / 'graph.json'
            result.graph.write(graph)
            if graph.stat().st_size > MAX_GRAPH:
                raise ValueError('Graph exceeds 128 MiB; narrow --graph-root')
            manifest.update(identity=identity, graph_sha256=hashlib.sha256(graph.read_bytes()).hexdigest(),
                            warnings=result.report.tallies(), build_ms=result.graph.build_ms)
            (publish / 'snapshot.json').write_text(json.dumps(manifest), encoding='utf-8')
            (publish / 'build-report.json').write_text(json.dumps(asdict(result.report)), encoding='utf-8')
            try:
                publish.rename(final)
            except OSError:
                if not final.exists():
                    raise
    manifest = json.loads((final / 'snapshot.json').read_text(encoding='utf-8'))
    graph = final / 'graph.json'
    if graph.stat().st_size > MAX_GRAPH:
        raise ValueError('Cached graph exceeds 128 MiB')
    raw = graph.read_bytes()
    if (manifest.get('identity') != identity or manifest.get('sha') != sha
            or manifest.get('graph_sha256') != hashlib.sha256(raw).hexdigest()):
        raise ValueError('Cached graph SHA/config/content hash mismatch')
    return graph, manifest, json.loads(raw), reused
