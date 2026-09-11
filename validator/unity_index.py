"""Disk-backed project index; ingest serialized assets one at a time.

Uses internal ingestion APIs of pinned UnityGraph 2.1.4. The official MCP server
receives a bounded graph projected from this index, never the entire database.
"""
from collections import Counter
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time

from .unity_snapshot import export_snapshot


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build_index(project, database):
    from unitygraph.build import builder as b
    from unitygraph.build.graph import Graph, Node, Edge, make_prefab_id, make_scene_id, make_shadergraph_id
    project = Path(project)
    started = time.monotonic()
    # Temporarily move serialized assets to a sibling staging directory, so the
    # global script pass does not accumulate every prefab and scene in memory.
    serialized = sorted(p for p in project.rglob('*') if p.suffix.lower() in
                        {'.prefab', '.unity', '.controller', '.shadergraph'})
    stash = project.parent / 'serialized'
    assets = []
    for path in serialized:
        relative = path.relative_to(project)
        moved = stash / relative
        moved.parent.mkdir(parents=True, exist_ok=True)
        path.rename(moved)
        assets.append((relative, moved))
    # Our export already excludes generated/worktree data. Do not let upstream
    # directory-name heuristics drop committed Assets/Build or Packages/*/obj.
    # This compatibility adapter runs only in the isolated index worker.
    discover, guid_builder = b._discover, b.meta_parser.build_guid_index
    try:
        b._discover = lambda root, pattern, **kwargs: discover(root, pattern, skip_generated=False)
        b.meta_parser.build_guid_index = lambda root: guid_builder(root, skip_dirs=())
        base = b.build_project(project)
    finally:
        b._discover, b.meta_parser.build_guid_index = discover, guid_builder
    guids = guid_builder(project, skip_dirs=())
    scripts = {}
    for path in b._discover(project, '*.cs', skip_generated=False):
        guid = b.meta_parser.load_meta_guid(path.with_suffix('.cs.meta'))
        try:
            classes = b.cs_parser.parse_file(path).classes
            if guid and classes:
                scripts[guid] = (next((c for c in classes if c.name == path.stem), classes[0]), path)
        except Exception as exc:
            base.report.warn('cs_parser', str(path.relative_to(project)), str(exc))
    prefabs = {}
    shaders = {}
    for relative, _ in assets:
        if relative.suffix == '.prefab':
            guid = b.meta_parser.load_meta_guid((project / relative).with_suffix('.prefab.meta'))
            if guid:
                prefabs[guid] = make_prefab_id(relative.stem, str(relative))
        if relative.suffix == '.shadergraph':
            guid = b.meta_parser.load_meta_guid((project / relative).with_suffix('.shadergraph.meta'))
            if guid:
                shaders[guid] = make_shadergraph_id(relative.stem, str(relative))
    warnings = Counter(base.report.tallies())
    counts = Counter()
    warning_sample = []
    with closing(sqlite3.connect(database)) as db:
        db.executescript('''
            CREATE TABLE nodes(id TEXT PRIMARY KEY, path TEXT, type TEXT, payload TEXT);
            CREATE TABLE edges(source TEXT, target TEXT, kind TEXT, payload TEXT);
            CREATE INDEX node_paths ON nodes(path);
        ''')

        def ingest(graph):
            for node in graph.nodes:
                value = node.to_json()
                value.pop('inspector_values', None)
                db.execute('INSERT OR IGNORE INTO nodes VALUES(?,?,?,?)',
                           (node.id, value.get('file_path', '').replace('\\', '/'), node.type, json.dumps(value)))
            for edge in graph.edges:
                value = edge.to_json()
                value.pop('inspector_values', None)
                db.execute('INSERT INTO edges VALUES(?,?,?,?)',
                           (edge.from_id, edge.to_id, edge.type, json.dumps(value)))

        ingest(base.graph)
        for relative, path in assets:
            graph = Graph(project_root=str(project))
            report = b.BuildReport()
            suffix = relative.suffix.lower()
            try:
                if suffix in {'.prefab', '.unity'}:
                    parsed = b.scene_parser.parse_file(path)
                    kind = 'Prefab' if suffix == '.prefab' else 'Scene'
                    scope = (make_prefab_id if kind == 'Prefab' else make_scene_id)(relative.stem, str(relative))
                    graph.add_node(Node(id=scope, type=kind, data={'name': relative.stem, 'file_path': str(relative)}))
                    b._ingest_scene(graph, scope, parsed, scripts, guids, report, scene_rel=str(relative))
                    b._emit_variant_edges(graph, [(scope, parsed, str(relative))], prefabs)
                else:
                    # These parsers derive file identity relative to project_root.
                    restored = project / relative
                    path.rename(restored)
                    try:
                        if suffix == '.controller':
                            b._ingest_animators(graph, [restored], project, report)
                        else:
                            b._ingest_shadergraphs(graph, [restored], project, report)
                            parsed_shader = b.shadergraph_parser.parse_file(restored)
                            source = make_shadergraph_id(relative.stem, str(relative))
                            for guid in parsed_shader.subgraph_refs:
                                target = shaders.get(guid)
                                if target and target != source:
                                    graph.add_edge(Edge(from_id=source, to_id=target, type='uses_subgraph'))
                    finally:
                        restored.rename(path)
                ingest(graph)
                counts[suffix] += 1
            except Exception as exc:
                report.warn('asset_parser', str(relative), str(exc))
            warnings.update(report.tallies())
            warning_sample.extend({'category': w.category, 'path': str(relative), 'message': w.message[:300]}
                                  for w in report.warnings[:max(0, 100 - len(warning_sample))])
            db.commit()
        db.executescript('CREATE INDEX edge_source ON edges(source); CREATE INDEX edge_target ON edges(target);')
        nodes = db.execute('SELECT count(*) FROM nodes').fetchone()[0]
        edges = db.execute('SELECT count(*) FROM edges').fetchone()[0]
    return {'warnings': dict(warnings), 'warning_sample': warning_sample, 'parsed_assets': dict(counts),
            'parsed_scripts': base.report.n_cs, 'nodes': nodes, 'edges': edges,
            'build_ms': int((time.monotonic() - started) * 1000)}


def index_cache(repo, prefix, sha, roots, cache):
    import unitygraph
    if unitygraph.__version__ != '2.1.4':
        raise ValueError('Streaming index requires unitygraph==2.1.4')
    identity = {'schema': 3, 'repo': str(Path(repo).resolve()), 'prefix': prefix, 'sha': sha,
                'roots': roots, 'version': unitygraph.__version__, 'format': 'sqlite-stream'}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cache = Path(cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    final = cache / key
    reused = final.exists()
    if not reused:
        with tempfile.TemporaryDirectory(prefix='index-staging-', dir=cache) as staging:
            stage = Path(staging)
            if os.name == 'nt':
                # Python's private temp-directory ACL otherwise survives rename
                # and locks the published cache to its creator (e.g. sandbox).
                # Inherit only the cache parent's existing permissions, before
                # creating artifacts, so publication remains atomic for readers.
                subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/icacls.exe'),
                                str(stage), '/inheritance:e'], check=True, timeout=10,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            manifest = export_snapshot(repo, prefix, sha, stage / 'project', roots, full=True)
            publish = stage / 'publish'
            publish.mkdir()
            report = build_index(stage / 'project', publish / 'index.sqlite')
            manifest.update(report, identity=identity, index_sha256=file_hash(publish / 'index.sqlite'))
            manifest['limitations'] = [
                'Registry/Git/external file packages and Library/PackageCache are not downloaded or indexed.',
                'Binary assets and unsupported formats (including general ScriptableObject .asset) have no parsed graph.',
                'Inspector payloads are omitted from the structural index; retrieve source to inspect serialized values.',
                'UnityGraph symbol resolution limitations remain; full file coverage is not semantic completeness.']
            (publish / 'snapshot.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            try:
                publish.rename(final)
            except OSError:
                if not final.exists():
                    raise
    manifest = json.loads((final / 'snapshot.json').read_text(encoding='utf-8'))
    database = final / 'index.sqlite'
    if manifest.get('identity') != identity or file_hash(database) != manifest.get('index_sha256'):
        raise ValueError('Index SHA/config/content hash mismatch')
    return database, manifest, reused


def neighborhood(database, paths, max_edges=400, max_bytes=512000):
    """Use indexed lookups rather than loading the whole graph into memory."""
    nodes, edges, truncated = {}, [], False
    remaining = max(0, max_bytes - 4096)

    def compact(payload):
        value = json.loads(payload)
        return {k: value[k] for k in ('id', 'type', 'name', 'file_path', 'namespace', 'scope',
                                      'external', 'component_type', 'class_line') if k in value}
    with closing(sqlite3.connect(f'{Path(database).resolve().as_uri()}?mode=ro', uri=True)) as db:
        seeds = []
        for path in paths:
            for row in db.execute("SELECT id,payload FROM nodes WHERE path=? AND type='Script'", (path,)):
                if len(seeds) >= 8:
                    truncated = True
                    break
                value = compact(row[1])
                size = len(json.dumps(value).encode())
                if size > remaining:
                    truncated = True
                    continue
                remaining -= size
                seeds.append(row[0])
                nodes[row[0]] = value
        seen = set()
        for seed in seeds:
            # UNION prevents returning a self-edge twice. Prefer actual dependencies
            # over co-location, but cap SQL output before materializing node payloads.
            rows = db.execute('''SELECT rowid,source,target,payload FROM edges
                                 WHERE source=? OR target=? ORDER BY kind='co_exists_with',rowid LIMIT ?''',
                              (seed, seed, max_edges + 1))
            for row_id, source, target, payload in rows:
                if row_id in seen:
                    continue
                seen.add(row_id)
                if len(edges) >= max_edges:
                    truncated = True
                    break
                added = {}
                for node_id in (source, target):
                    if node_id not in nodes:
                        row = db.execute('SELECT payload FROM nodes WHERE id=?', (node_id,)).fetchone()
                        if row:
                            added[node_id] = compact(row[0])
                size = len(payload.encode()) + sum(len(json.dumps(n).encode()) for n in added.values())
                if size > remaining:
                    truncated = True
                    continue
                remaining -= size
                nodes.update(added)
                edges.append(json.loads(payload))
    return {'project_root': 'immutable-snapshot', 'nodes': list(nodes.values()), 'edges': edges}, truncated
