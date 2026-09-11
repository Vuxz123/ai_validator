import importlib.util
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

from test_lifecycle import RepoCase, ROOT


class UnityMcpTests(RepoCase):
    def make_project(self):
        self.commit('Game/Assets/Caller.cs', 'class Caller { void Go() { Reward.Instance.Show(); } }\n')
        return self.commit('Game/Assets/Reward.cs', 'class Reward { public void Show() {} }\n')

    def test_snapshot_excludes_working_edits_and_signing_files(self):
        from validator.unity_snapshot import export_snapshot
        sha = self.make_project()
        sha = self.commit('Game/Assets/Keystore/secret.meta', 'sensitive')
        (self.repo / 'Game/Assets/Reward.cs').write_text('DIRTY')
        out = self.root / 'snapshot'
        manifest = export_snapshot(str(self.repo), 'Game/', sha, out, ['Assets'])
        self.assertIn('class Reward', (out / 'Assets/Reward.cs').read_text())
        self.assertFalse((out / 'Assets/Keystore').exists())
        self.assertEqual(manifest['sha'], sha)

    def test_singleton_search_returns_git_paths_and_source(self):
        from validator.unity_mcp import text_context
        sha = self.make_project()
        data = text_context(str(self.repo), 'Game/', sha, ['Game/Assets/Reward.cs'], time.monotonic() + 30)
        self.assertIn('Game/Assets/Caller.cs', data['files'])
        self.assertTrue(any(m['file'] == 'Game/Assets/Caller.cs' for m in data['matches']))
        self.assertEqual(data['sha'], sha)

    def test_nested_routing_and_graph_failure_are_advisory(self):
        self.make_project()
        self.order('a')
        self.cli('confirm', 'a')
        self.commit('Game/Assets/Reward.cs', 'class Reward { public void Show() { } }\n')
        self.order('b')
        from validator.runner import analyze
        from validator.store import Store
        with patch('validator.unity_mcp.collect', return_value={
                'status': 'ERROR', 'limitations': ['MCP unavailable'], 'files': {}}):
            result = analyze(Store(self.db), 'b', ROOT / 'workflows', unity_project=str(self.repo / 'Game'))
        self.assertEqual(result['analysis_status'], 'COMPLETED')
        self.assertEqual(result['report']['assessment'], 'INCOMPLETE')
        self.assertIn('code_impact', result['report']['selected_workflows'])
        self.assertIn('Game/Assets/Reward.cs', result['report']['context']['files'])
        self.assertIsNone(result['confirmed_at'])

    def test_worker_forwards_graph_options(self):
        from argparse import Namespace
        from validator.__main__ import start_worker
        from validator.store import Store
        args = Namespace(workflows=str(ROOT / 'workflows'), timeout=10, budget=20,
                         agent_command=None, backend=None, model=None, agent_executable=None,
                         unity_project=str(self.repo), graph_timeout=12, graph_root=['Assets'])
        with patch('validator.__main__.subprocess.Popen') as popen:
            start_worker(Store(self.db), 'b', args)
        command = popen.call_args.args[0]
        self.assertIn('--unity-project', command)
        self.assertEqual(command[command.index('--graph-timeout') + 1], '12')

    def test_official_mcp_and_cache_hash(self):
        if importlib.util.find_spec('unitygraph') is None:
            self.skipTest('Optional UnityGraph dependency not installed')
        from validator.unity_mcp import collect
        sha = self.make_project()
        build = {'repo': str(self.repo), 'target_sha': sha, 'baseline_sha': sha}
        data = collect(build, ['Game/Assets/Reward.cs'], 'Game/', self.root / 'cache',
                       ['Assets'], time.monotonic() + 60)
        self.assertEqual(data['status'], 'COMPLETED', data)
        target = data['snapshots']['target']
        self.assertEqual(target['transport'], 'mcp-stdio')
        self.assertTrue(target['queries'][0]['result']['found'])
        manifest_path = Path(target['manifest_path'])
        graph = manifest_path.parent / 'index.sqlite'
        graph.write_text('{}')
        # Tampered cache must be rejected, never queried or silently trusted.
        data = collect(build, ['Game/Assets/Reward.cs'], 'Game/', self.root / 'cache',
                       ['Assets'], time.monotonic() + 60)
        self.assertEqual(data['status'], 'ERROR')
        self.assertIn('hash', ' '.join(data['limitations']).lower())

    def test_nested_texture_evidence_keeps_repo_prefix(self):
        self.make_project()
        self.order('a')
        self.cli('confirm', 'a')
        self.commit('Game/Assets/icon.png', 'fake image')
        self.order('b')
        result = self.cli('analyze', 'b', '--unity-project', str(self.repo / 'Game'))
        check = next(c for c in result['report']['checks'] if c['check_id'] == 'TEXTURE_META_001')
        self.assertEqual(check['status'], 'FAIL')
        self.assertEqual(check['evidence'][0]['file'], 'Game/Assets/icon.png.meta')

    def test_runner_preserves_existing_context_omissions(self):
        self.make_project()
        self.order('a')
        self.cli('confirm', 'a')
        self.commit('Game/Assets/Reward.cs', 'class Reward { int x; }\n')
        self.order('b')
        from validator.runner import analyze
        from validator.store import Store
        from validator.git import context_for
        build = Store(self.db).get('b')
        context = context_for(build)
        context['limitations'].append('Diff truncated to context budget.')
        with patch('validator.runner.context_for', return_value=context), patch(
                'validator.unity_mcp.collect', return_value={
                    'status': 'ERROR', 'limitations': ['MCP unavailable'], 'files': {}}):
            result = analyze(Store(self.db), 'b', ROOT / 'workflows', unity_project=str(self.repo / 'Game'))
        self.assertIn('Diff truncated to context budget.', result['report']['limitations'])

    def test_expired_graph_deadline_is_advisory(self):
        from validator.unity_mcp import collect
        sha = self.make_project()
        data = collect({'repo': str(self.repo), 'target_sha': sha, 'baseline_sha': sha},
                       ['Game/Assets/Reward.cs'], 'Game/', self.root / 'cache', ['Assets'],
                       time.monotonic() - 1)
        self.assertEqual(data['status'], 'ERROR')
        self.assertIn('budget exhausted', ' '.join(data['limitations']))

    def test_other_project_names_do_not_exhaust_caller_budget(self):
        from validator.unity_mcp import text_context
        sha = self.make_project()
        changed = [f'Other/Assets/A{i}.cs' for i in range(8)] + ['Game/Assets/Reward.cs']
        result = text_context(str(self.repo), 'Game/', sha, changed, time.monotonic() + 30)
        self.assertIn('Game/Assets/Caller.cs', result['files'])

    def test_large_caller_does_not_starve_smaller_callers(self):
        from validator.unity_mcp import text_context
        self.make_project()
        self.commit('Game/Assets/AAALarge.cs', 'Reward.Instance.Show();\n' + ' ' * 59000)
        sha = self.commit('Game/Assets/ZSmall.cs', 'Reward.Instance.Show();\n' + ' ' * 2000)
        result = text_context(str(self.repo), 'Game/', sha, ['Game/Assets/Reward.cs'], time.monotonic() + 30)
        self.assertIn('Game/Assets/ZSmall.cs', result['files'])

    def test_deleted_script_uses_baseline_but_only_target_evidence(self):
        if importlib.util.find_spec('unitygraph') is None:
            self.skipTest('Optional UnityGraph dependency not installed')
        self.make_project()
        self.order('a')
        self.cli('confirm', 'a')
        self.git('rm', 'Game/Assets/Reward.cs')
        self.git('commit', '-qm', 'Remove Reward')
        self.order('b')
        result = self.cli('analyze', 'b', '--unity-project', str(self.repo / 'Game'))
        context = result['report']['context']
        snapshots = context['unitygraph']['snapshots']
        self.assertEqual(snapshots['target']['queries'], [])
        self.assertTrue(snapshots['baseline']['queries'][0]['result']['found'])
        self.assertIn('Game/Assets/Caller.cs', context['files'])
        self.assertNotIn('Game/Assets/Reward.cs', context['files'])
        from validator.agent import validate_evidence
        with self.assertRaises(ValueError):
            validate_evidence([{'sha': result['baseline_sha'], 'file': 'Game/Assets/Reward.cs',
                                'line': 1, 'reason': 'removed'}], result, context)

    def test_oversized_snapshot_asset_is_reported_and_omitted(self):
        from validator.unity_snapshot import export_snapshot
        sha = self.commit('Game/Assets/Large.prefab', 'x' * (4 * 1024 * 1024 + 1))
        out = self.root / 'snapshot'
        manifest = export_snapshot(str(self.repo), 'Game/', sha, out, ['Assets'])
        self.assertEqual(manifest['omitted_count'], 1)
        self.assertFalse((out / 'Assets/Large.prefab').exists())

    def test_live_worker_deadline_returns_error_without_confirming(self):
        from validator.unity_mcp import collect
        sha = self.make_project()
        start = time.monotonic()
        data = collect({'repo': str(self.repo), 'target_sha': sha, 'baseline_sha': sha},
                       ['Game/Assets/Reward.cs'], 'Game/', self.root / 'cache', ['Assets'], start + 0.05)
        self.assertEqual(data['status'], 'ERROR')
        self.assertLess(time.monotonic() - start, 15)
