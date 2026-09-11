import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

from test_lifecycle import RepoCase


class UnityIndexTests(RepoCase):
    def test_windows_cache_preserves_parent_user_access(self):
        if os.name != 'nt' or importlib.util.find_spec('unitygraph') is None:
            self.skipTest('Windows and optional UnityGraph required')
        from validator.unity_index import index_cache
        user = subprocess.check_output(['whoami'], text=True).strip()
        cache = self.root / 'cache'
        cache.mkdir()
        subprocess.run(['icacls', str(cache), '/grant', user + ':(OI)(CI)(RX)'],
                       check=True, capture_output=True)
        database, _, _ = index_cache(str(self.repo), '', self.a, ['Assets', 'Packages'], cache)
        for path in (database, database.parent / 'snapshot.json'):
            acl = subprocess.check_output(['icacls', str(path)], text=True)
            self.assertIn(user.lower(), acl.lower())

    def test_full_export_includes_packages_and_large_supported_files(self):
        from validator.unity_snapshot import export_snapshot
        self.commit('Game/Packages/com.test/Caller.cs', 'class Caller {}')
        sha = self.commit('Game/Assets/Large.prefab', 'x' * (4 * 1024 * 1024 + 1))
        out = self.root / 'snapshot'
        manifest = export_snapshot(str(self.repo), 'Game/', sha, out, ['Assets', 'Packages'], full=True)
        self.assertTrue((out / 'Packages/com.test/Caller.cs').exists())
        self.assertTrue((out / 'Assets/Large.prefab').exists())
        self.assertEqual(manifest['omitted_count'], 0)

    def test_index_keeps_cross_file_attachments_and_bounded_query(self):
        if importlib.util.find_spec('unitygraph') is None:
            self.skipTest('optional UnityGraph dependency')
        from validator.unity_index import index_cache, neighborhood
        self.commit('Game/Packages/com.test/Reward.cs', 'class Reward {}')
        self.commit('Game/Packages/com.test/Reward.cs.meta', 'guid: ' + 'a' * 32)
        prefab = '''%YAML 1.1
--- !u!1 &1
GameObject:
  m_Component:
  - component: {fileID: 2}
  m_Name: Owner
--- !u!114 &2
MonoBehaviour:
  m_GameObject: {fileID: 1}
  m_Script: {fileID: 11500000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 3}
'''
        sha = self.commit('Game/Assets/Owner.prefab', prefab)
        db, manifest, reused = index_cache(str(self.repo), 'Game/', sha, ['Assets', 'Packages'], self.root / 'cache')
        with closing(sqlite3.connect(db)) as connection:
            self.assertGreater(connection.execute('select count(*) from edges').fetchone()[0], 0)
        data, truncated = neighborhood(db, ['Packages/com.test/Reward.cs'])
        self.assertTrue(any(e['type'] == 'attached_to' for e in data['edges']))
        self.assertTrue(any(n.get('name') == 'Owner' for n in data['nodes']))
        self.assertFalse(truncated)
        self.assertEqual(manifest['omitted_count'], 0)
        self.assertTrue(index_cache(str(self.repo), 'Game/', sha, ['Assets', 'Packages'], self.root / 'cache')[2])
        with db.open('ab') as stream:
            stream.write(b'tamper')
        with self.assertRaisesRegex(ValueError, 'hash'):
            index_cache(str(self.repo), 'Game/', sha, ['Assets', 'Packages'], self.root / 'cache')

    def test_package_caller_search(self):
        from validator.unity_mcp import text_context
        self.commit('Game/Packages/com.test/Reward.cs', 'class Reward {}')
        sha = self.commit('Game/Assets/Caller.cs', 'class Caller { void Go() { Reward.Instance.Show(); } }')
        data = text_context(str(self.repo), 'Game/', sha, ['Game/Packages/com.test/Reward.cs'], time.monotonic() + 30)
        self.assertIn('Game/Assets/Caller.cs', data['files'])

    def test_prewarm_cli_uses_full_default_roots(self):
        if importlib.util.find_spec('unitygraph') is None:
            self.skipTest('optional UnityGraph dependency')
        self.commit('Game/Packages/com.test/Foo.cs', 'class Foo {}')
        result = self.cli('index-unity', '--repo', str(self.repo / 'Game'), '--target', 'HEAD')
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(result['manifest']['include_roots'], ['Assets', 'Packages'])
        self.assertEqual(result['manifest']['parsed_scripts'], 1)

    def test_large_seed_metadata_is_bounded(self):
        from validator.unity_index import neighborhood
        path = self.root / 'large.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.executescript('CREATE TABLE nodes(id,path,type,payload); CREATE TABLE edges(source,target,kind,payload);')
            node = {'id': 'seed', 'type': 'Script', 'file_path': 'Assets/Big.cs', 'methods': ['x' * 600000]}
            db.execute('INSERT INTO nodes VALUES(?,?,?,?)', ('seed', 'Assets/Big.cs', 'Script', json.dumps(node)))
            db.commit()
        data, truncated = neighborhood(path, ['Assets/Big.cs'])
        self.assertLess(len(json.dumps(data).encode()), 512000)

    def test_shader_references_cross_asset_boundaries(self):
        if importlib.util.find_spec('unitygraph') is None:
            self.skipTest('optional UnityGraph dependency')
        from validator.unity_index import index_cache
        self.commit('Game/Assets/Base.shadergraph', '{}')
        self.commit('Game/Assets/Base.shadergraph.meta', 'guid: ' + 'b' * 32)
        sha = self.commit('Game/Assets/Main.shadergraph', json.dumps({
            'm_Type': 'UnityEditor.ShaderGraph.SubGraphNode', 'm_SubGraphGuid': 'b' * 32}))
        path, _, _ = index_cache(str(self.repo), 'Game/', sha, ['Assets', 'Packages'], self.root / 'cache')
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM edges WHERE kind='uses_subgraph'").fetchone()[0], 1)

    def test_committed_build_directory_is_indexed(self):
        if importlib.util.find_spec('unitygraph') is None:
            self.skipTest('optional UnityGraph dependency')
        from validator.unity_index import index_cache, neighborhood
        sha = self.commit('Game/Assets/Build/Release.cs', 'class Release {}')
        path, manifest, _ = index_cache(str(self.repo), 'Game/', sha, ['Assets', 'Packages'], self.root / 'cache')
        data, _ = neighborhood(path, ['Assets/Build/Release.cs'])
        self.assertEqual(manifest['parsed_scripts'], 1)
        self.assertTrue(data['nodes'])

    def test_prefab_variant_resolves_base_in_another_file(self):
        if importlib.util.find_spec('unitygraph') is None:
            self.skipTest('optional UnityGraph dependency')
        from validator.unity_index import index_cache
        self.commit('Game/Assets/ZBase.prefab', '%YAML 1.1\n--- !u!1 &1\nGameObject:\n  m_Name: Base\n')
        self.commit('Game/Assets/ZBase.prefab.meta', 'guid: ' + 'c' * 32)
        sha = self.commit('Game/Assets/AVariant.prefab',
                          '%YAML 1.1\n--- !u!1001 &1\nPrefabInstance:\n  m_SourcePrefab: {fileID: 100100000, guid: '
                          + 'c' * 32 + ', type: 3}\n')
        path, _, _ = index_cache(str(self.repo), 'Game/', sha, ['Assets', 'Packages'], self.root / 'cache')
        with closing(sqlite3.connect(path)) as db:
            edge = db.execute("SELECT source,target FROM edges WHERE kind='is_variant_of'").fetchone()
            self.assertIsNotNone(edge)
            self.assertIn('AVariant', edge[0])
            self.assertIn('ZBase', edge[1])
