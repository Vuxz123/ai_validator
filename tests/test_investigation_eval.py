import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from examples.evaluate_investigation import load_cases, score, prepare, ROOT
from validator.runner import analyze


class InvestigationEvalTests(unittest.TestCase):
    def test_false_positive_cases_keep_real_baselines_and_scoped_expectations(self):
        import subprocess
        cases = load_cases()
        names = ('caller_guard', 'unreachable_method', 'preexisting_defect', 'namespace_collision')
        with tempfile.TemporaryDirectory() as directory:
            for name in names:
                with self.subTest(case=name):
                    case = cases[name]
                    self.assertEqual(case['expected'], dict(status='PASS', findings=[]))
                    store, _, _ = prepare(Path(directory), name, cases)
                    build = store.get('target')
                    for snapshot, files in [('baseline', case['baseline_files']),
                                            ('target', {**case['baseline_files'], **case['files']})]:
                        for path, source in files.items():
                            actual = subprocess.check_output(['git', '-C', build['repo'], 'show',
                                     build[snapshot+'_sha']+':'+path]).decode('utf-8')
                            self.assertEqual(actual.replace('\r\n', '\n'), source)
                    changed = subprocess.check_output(['git', '-C', build['repo'], 'diff', '--name-only',
                              build['baseline_sha'], build['target_sha']]).decode('utf-8')
                    self.assertTrue(changed.strip())

    def test_sdk_finding_runs_independent_verify_and_scores_ownership(self):
        cases = load_cases()
        with tempfile.TemporaryDirectory() as directory:
            store, config, expected = prepare(Path(directory), 'sdk_callback', cases)
            sha = store.get('target')['target_sha']
            evidence = [dict(sha=sha, file='Game/Assets/Vendor/Factory.cs', line=4, reason='Callback branch'),
                        dict(sha=sha, file='Game/Assets/Feature/Scenario.cs', line=4, reason='Caller')]
            finding = dict(check_id='CODE_IMPACT_001', status='FAIL', summary='Two callbacks',
                           evidence=evidence, limitations=[])
            response = dict(action='finish', requests=[], findings=[finding], status='FAIL',
                            summary='Candidate', evidence=evidence, limitations=[])
            def verify(command, request, timeout):
                self.assertEqual(request['phase'], 'verify')
                self.assertNotIn('summary_any', str(request))
                return dict(verdict='CONFIRMED', summary='Fixture verification', evidence=evidence)
            retrieval = dict(action='retrieve', requests=[dict(kind='read',
                             path='Game/Assets/Feature/Scenario.cs', query='', snapshot='target')],
                             findings=[], status='UNKNOWN', summary='Read caller', evidence=[], limitations=[])
            with patch('validator.investigation.invoke', side_effect=[retrieval, response]), \
                    patch('validator.runner.invoke', side_effect=verify) as verifier:
                result = analyze(store, 'target', ROOT / 'workflows', backend='codex',
                                 project_config=config, fixture_execution=cases['sdk_callback']['execution'])
            check = next(c for c in result['report']['checks'] if c['check_id'] == 'CODE_IMPACT_001')
            self.assertEqual(verifier.call_count, 1)
            self.assertTrue(score(expected, check)['matched'])

    def test_scoring_requires_identity_ownership_and_no_extra_findings(self):
        expected = dict(status='FAIL', findings=[dict(file='Game/Assets/Feature/Subject.cs',
                       start_line=2, end_line=4, ownership='first_party', summary_any=['null'])])
        finding = dict(status='FAIL', verified=True, execution_status='COMPLETED', summary='Null access',
                       evidence=[dict(file='Game/Assets/Feature/Subject.cs', line=3)],
                       source_ownership=[dict(file='Game/Assets/Feature/Subject.cs', ownership='first_party')])
        check = dict(status='FAIL', verified=True, execution_status='COMPLETED',
                     investigation=dict(findings=[finding], stop_reason='agent_finished'))
        self.assertTrue(score(expected, check)['matched'])
        for field, value in [('summary', 'Unrelated bug'), ('verified', False),
                             ('source_ownership', []), ('evidence', [])]:
            bad = copy.deepcopy(check)
            bad['investigation']['findings'][0][field] = value
            self.assertFalse(score(expected, bad)['matched'])
        check['investigation']['findings'].append(copy.deepcopy(finding))
        self.assertFalse(score(expected, check)['matched'])
        for status in ('ERROR', 'TIMEOUT'):
            self.assertFalse(score(dict(status='UNKNOWN', findings=[]),
                                   dict(status='UNKNOWN', execution_status=status))['matched'])

    def test_unknown_caps_and_tool_errors_are_not_semantic_matches(self):
        expected = dict(status='UNKNOWN', findings=[])
        check = dict(status='UNKNOWN', execution_status='COMPLETED',
                     investigation=dict(findings=[], stop_reason='agent_finished'))
        self.assertTrue(score(expected, check)['matched'])
        check['investigation']['stop_reason'] = 'round_limit'
        self.assertFalse(score(expected, check)['matched'])
        check['investigation']['stop_reason'] = 'agent_finished'
        check['investigation_context'] = dict(tool_results=[dict(error='Git timeout')])
        self.assertFalse(score(expected, check)['matched'])

    def test_custom_cases_reject_unsafe_paths_and_invalid_anchors(self):
        import yaml
        case = copy.deepcopy(load_cases()['project_null'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'custom.yaml'
            for filename in ('../escape.cs', '.git/config', 'C:/escape.cs'):
                bad = copy.deepcopy(case)
                bad['baseline_files'] = {filename: 'text'}
                path.write_text(yaml.safe_dump(bad))
                with self.assertRaises(ValueError):
                    load_cases(directory)
            case['expected']['findings'][0]['end_line'] = 999
            path.write_text(yaml.safe_dump(case))
            with self.assertRaises(ValueError):
                load_cases(directory)

    def test_cases_use_open_flow_and_hide_rubrics(self):
        cases = load_cases()
        with tempfile.TemporaryDirectory() as directory:
            for name, case in cases.items():
                store, config, _ = prepare(Path(directory), name, cases)
                seen = []
                def agent(command, request, timeout):
                    seen.append(request['phase'])
                    self.assertEqual(request['phase'], 'investigate')
                    self.assertNotIn(name, request['build']['repo'])
                    self.assertNotIn('expected', request['context'])
                    self.assertNotIn('summary_any', str(request))
                    return dict(action='finish', requests=[], findings=[], status='UNKNOWN',
                                summary='Fake agent; no accuracy claim.', evidence=[], limitations=[])
                with patch('validator.investigation.invoke', side_effect=agent):
                    result = analyze(store, 'target', ROOT / 'workflows', backend='codex',
                                     project_config=config, fixture_execution=case['execution'])
                self.assertEqual(seen, ['investigate'])
                self.assertEqual(result['report']['assessment_scope'], 'synthetic_fixture')
                self.assertIsNone(store.get('target')['confirmed_at'])
                self.assertIn('code_impact', result['report']['selected_workflows'])
