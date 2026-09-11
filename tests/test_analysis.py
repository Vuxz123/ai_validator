import json
import sys
import time

from test_lifecycle import RepoCase, ROOT


class AnalysisTests(RepoCase):
    def test_missing_backend_is_unknown_and_first_build_still_has_report(self):
        missing = str(self.root / 'missing.exe')
        self.order('first')
        first = self.cli('analyze', 'first', '--backend', 'codex', '--agent-executable', missing)
        self.assertEqual(first['report']['assessment'], 'NO_BASELINE')
        self.prepare_delta()
        report = self.analyze('--backend', 'opencode', '--agent-executable', missing)
        self.assertEqual(report['backend'], 'opencode')
        self.assertEqual(report['assessment'], 'INCOMPLETE')
        check = next(c for c in report['checks'] if c['check_id'] == 'ADS_REWARD_001')
        self.assertEqual(check['execution_status'], 'ERROR')

    def prepare_delta(self):
        self.order('a')
        self.cli('confirm', 'a')
        self.b = self.commit('Assets/Scripts/Ads/Reward.cs', 'class Reward { int coins; }\n')
        self.order('b')

    def agent_config(self, mode):
        file = self.root / 'agent.json'
        file.write_text(json.dumps([sys.executable, str(ROOT / 'tests/fixture_agent.py'), mode]))
        return str(file)

    def analyze(self, *args):
        return self.cli('analyze', 'b', *args)['report']

    def test_first_build_is_no_baseline_not_pass(self):
        self.order('b')
        result = self.cli('analyze', 'b')
        self.assertEqual(result['analysis_status'], 'COMPLETED')
        self.assertEqual(result['report']['assessment'], 'NO_BASELINE')

    def test_selects_ads_and_missing_agent_is_unknown(self):
        self.prepare_delta()
        report = self.analyze()
        self.assertIn('rewarded_ads', report['selected_workflows'])
        self.assertNotIn('unity_lifecycle', report['selected_workflows'])
        checks = {c['check_id']: c for c in report['checks']}
        self.assertEqual(checks['ADS_REWARD_001']['status'], 'UNKNOWN')
        self.assertEqual(report['assessment'], 'INCOMPLETE')
        self.assertTrue(report['limitations'])

    def test_immutable_context_and_verified_finding(self):
        self.prepare_delta()
        (self.repo / 'Assets/Scripts/Ads/Reward.cs').write_text('dirty local file')
        report = self.analyze('--agent-command', self.agent_config('confirm'))
        self.assertEqual(report['assessment'], 'FINDINGS')
        check = next(c for c in report['checks'] if c['check_id'] == 'ADS_REWARD_001')
        self.assertTrue(check['verified'])
        self.assertEqual(check['evidence'][0]['sha'], self.b)
        self.assertIn('int coins', report['context']['files']['Assets/Scripts/Ads/Reward.cs'])
        self.assertNotIn('dirty', json.dumps(report))

    def test_rejected_finding_becomes_unknown_not_pass(self):
        self.prepare_delta()
        report = self.analyze('--agent-command', self.agent_config('reject'))
        check = next(c for c in report['checks'] if c['check_id'] == 'ADS_REWARD_001')
        self.assertFalse(check['verified'])
        self.assertEqual(check['status'], 'UNKNOWN')
        self.assertEqual(check['verification']['verdict'], 'REJECTED')

    def test_bad_evidence_and_malformed_agent_output_are_unknown(self):
        self.prepare_delta()
        for mode in ('bad_line', 'invalid'):
            with self.subTest(mode=mode):
                report = self.analyze('--retry', '--agent-command', self.agent_config(mode))
                check = next(c for c in report['checks'] if c['check_id'] == 'ADS_REWARD_001')
                self.assertEqual(check['status'], 'UNKNOWN')
                self.assertEqual(check['execution_status'], 'ERROR')

    def test_timeout_is_recorded_without_confirming(self):
        self.prepare_delta()
        report = self.analyze('--agent-command', self.agent_config('timeout'), '--timeout', '0.1')
        check = next(c for c in report['checks'] if c['check_id'] == 'ADS_REWARD_001')
        self.assertEqual(check['execution_status'], 'TIMEOUT')
        self.assertIsNone(self.cli('report', 'b')['confirmed_at'])

    def test_invalid_yaml_fails_analysis_explicitly(self):
        self.prepare_delta()
        folder = self.root / 'workflows'
        folder.mkdir()
        (folder / 'bad.yaml').write_text('id: broken\nchecks: []\nunknown: true\n')
        self.cli('analyze', 'b', '--workflows', str(folder), success=False)
        self.assertEqual(self.cli('report', 'b')['analysis_status'], 'FAILED')

    def test_detached_order_finishes_without_confirming(self):
        ordered = self.cli('order', '--repo', str(self.repo), '--branch', 'main', '--target', self.a)
        self.assertTrue(ordered['worker_started'])
        for _ in range(40):
            report = self.cli('report', ordered['build_id'])
            if report['analysis_status'] in ('COMPLETED', 'FAILED'):
                break
            time.sleep(0.1)
        self.assertEqual(report['analysis_status'], 'COMPLETED')
        self.assertIsNone(report['confirmed_at'])

    def test_endpoint_diff_when_target_diverges(self):
        self.commit('baseline_only.txt', 'baseline')
        self.order('baseline')
        self.cli('confirm', 'baseline')
        self.git('checkout', '--detach', self.a)
        self.commit('target_only.txt', 'target')
        self.order('b')
        report = self.analyze()
        self.assertIn('baseline_only.txt', report['changed_files'])
        self.assertIn('target_only.txt', report['changed_files'])

    def test_rename_out_of_ads_still_selects_ads(self):
        self.order('a')
        self.cli('confirm', 'a')
        self.git('mv', 'Assets/Scripts/Ads/Reward.cs', 'Reward.cs')
        self.git('commit', '-qm', 'Move reward code')
        self.order('b')
        report = self.analyze()
        self.assertIn('rewarded_ads', report['selected_workflows'])
        self.assertIn('Assets/Scripts/Ads/Reward.cs', report['changed_files'])

    def test_git_output_limit_and_expired_deadline(self):
        from validator.git import git
        with self.assertRaisesRegex(ValueError, 'output limit'):
            git(self.repo, 'show', f'{self.a}:Assets/Scripts/Ads/Reward.cs', max_bytes=5)
        with self.assertRaises(TimeoutError):
            git(self.repo, 'rev-parse', 'HEAD', deadline=time.monotonic() - 1)
