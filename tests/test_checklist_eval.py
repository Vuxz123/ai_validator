import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml

from examples.checklist_cases import CASES
from examples.evaluate_checklists import prepare, score, ROOT
from validator.runner import analyze


class ChecklistEvalTests(unittest.TestCase):
    def test_fixture_execution_reaches_review_and_verify(self):
        execution = {'entrypoint': 'Scenario.Run', 'assumption': 'Called once in this synthetic scenario.'}
        with tempfile.TemporaryDirectory() as directory:
            store, config, _ = prepare(Path(directory), 'ads_bad')
            phases = []
            def agent(command, request, timeout):
                phases.append(request['phase'])
                self.assertEqual(request['context']['fixture_execution'], execution)
                self.assertNotIn('expected', request['context'])
                evidence = [dict(sha=request['build']['target_sha'],
                                file='Game/Assets/Feature/Subject.cs', line=1, reason='Fixture evidence')]
                if request['phase'] == 'verify':
                    return dict(verdict='REJECTED', summary='Fake rejection still respected.', evidence=evidence)
                return dict(check_id=request['check']['id'], status='FAIL', summary='Fake finding',
                            evidence=evidence, limitations=[])
            with patch('validator.runner.invoke', side_effect=agent):
                result = analyze(store, 'target', ROOT / 'workflows', backend='codex',
                                 project_config=config, fixture_execution=execution)
            self.assertIn('verify', phases)
            self.assertEqual(result['report']['assessment_scope'], 'synthetic_fixture')
            self.assertTrue(all(not c['verified'] for c in result['report']['checks']))

    def test_custom_yaml_case_and_path_rejection(self):
        from examples.checklist_cases import load_cases
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = dict(id='custom_flow', project=dict(unity_root='Game',
                        source_groups={'ui': ['Assets/Feature/**']}, rule_packs=['unity_lifecycle']),
                        files={'Game/Assets/Feature/Custom.cs': 'class Custom {}'},
                        expected={'UNITY_UI_004': 'UNKNOWN'})
            path = root / 'custom.yaml'
            path.write_text(yaml.safe_dump(data))
            cases = load_cases(root)
            store, _, expected = prepare(root / 'output', 'custom_flow', cases)
            self.assertEqual(expected, data['expected'])
            self.assertTrue((Path(store.get('target')['repo']) / 'Game/Assets/Feature/Custom.cs').exists())
            for invalid in ('../escape.cs', '.git/config', 'C:/escape.cs'):
                data['files'] = {invalid: 'text'}
                path.write_text(yaml.safe_dump(data))
                with self.assertRaises(ValueError):
                    load_cases(root)
    def test_errors_do_not_count_as_correct_unknown_and_fail_requires_verify(self):
        for status, execution, verified in [('UNKNOWN', 'ERROR', False),
                                            ('UNKNOWN', 'TIMEOUT', False),
                                            ('FAIL', 'COMPLETED', False)]:
            rows = score({'CHECK': status}, {'checks': [dict(check_id='CHECK', status=status,
                         execution_status=execution, verified=verified)]})
            self.assertFalse(rows[0]['matched'])
        self.assertFalse(score({'CHECK': 'PASS'}, {})[0]['matched'])
        for label in ('PASS', 'FAIL', 'UNKNOWN'):
            self.assertTrue(score({'CHECK': label}, {'checks': [dict(check_id='CHECK',
                status=label, execution_status='COMPLETED', verified=label == 'FAIL') ]})[0]['matched'])

    def test_all_cases_route_and_labels_are_not_in_agent_context(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in CASES:
                with self.subTest(case=name):
                    store, config, expected = prepare(Path(directory), name)
                    def agent(command, request, timeout):
                        self.assertNotIn('fixture_execution', request['context'])
                        self.assertNotIn(name, request['build']['repo'])
                        self.assertNotIn('expected', request)
                        self.assertNotIn('expected', request['context'])
                        self.assertTrue(request['check']['objective'])
                        self.assertTrue(request['check']['instructions'])
                        self.assertTrue(request['check']['context_requests'])
                        self.assertIn('unknown', request['check']['verdicts'])
                        return dict(check_id=request['check']['id'], status='UNKNOWN',
                                    summary='Fixture adapter; no semantic assessment.',
                                    evidence=[], limitations=[])
                    with patch('validator.runner.invoke', side_effect=agent):
                        result = analyze(store, 'target', ROOT / 'workflows', backend='codex',
                                         project_config=config)
                    report = result['report']
                    self.assertNotIn('code_impact', report['selected_workflows'])
                    actual = {c['check_id'] for c in report['checks']} - {'GIT_SNAPSHOT_001'}
                    self.assertEqual(actual, set(expected))
                    self.assertEqual(report['target_sha'], store.get('target')['target_sha'])
                    self.assertIsNone(store.get('target')['confirmed_at'])

    def test_bad_cases_include_local_reachable_scenario_for_verification(self):
        from validator.verification_context import collect
        with tempfile.TemporaryDirectory() as directory:
            for name in ('ads_bad', 'ui_bad'):
                store, _, _ = prepare(Path(directory), name)
                extra = collect(store.get('target'), {'evidence': [
                    {'file': 'Game/Assets/Feature/Subject.cs'}]}, time.monotonic() + 20)
                self.assertTrue(extra['complete'])
                self.assertIn('public class Scenario', extra['files']['Game/Assets/Feature/Subject.cs'])
