import time
import subprocess
from unittest.mock import patch
from test_lifecycle import RepoCase
import test_verification_context


class ReviewRetryTests(RepoCase):
    setup_finding = test_verification_context.VerificationContextTests.setup_finding

    def test_summary_factory_wins_over_many_limitation_names(self):
        from validator.review_context import collect
        build, finding = self.setup_finding()
        distractions = ['Game/Assets/A%d.cs' % i for i in range(6)]
        context = dict(files={}, changed_files=distractions + ['Game/Assets/Factory.cs'])
        review = dict(finding, status='UNKNOWN', evidence=[], summary='Factory.Create caller missing',
                      limitations=['Missing A0 A1 A2 A3 A4 A5'])
        extra = collect(build, review, context, time.monotonic() + 30)
        self.assertEqual(extra['seed_files'][0], 'Game/Assets/Factory.cs')
        self.assertIn('Game/Assets/Platform.cs', extra['files'])
    def run_unknown(self, responses):
        from validator.runner import run_check
        build, finding = self.setup_finding()
        context = dict(files={'Game/Assets/Factory.cs': 'class Factory {}'},
                       changed_files=['Game/Assets/Factory.cs'], limitations=[])
        first = dict(finding, status='UNKNOWN', evidence=[],
                     summary='Factory.Create caller context missing')
        with patch('validator.runner.invoke', side_effect=[first] + responses) as agent:
            result = run_check(dict(id='TEST_001', severity='high', executor='agent'),
                               build, context, ['fixture'], 30, time.monotonic() + 60)
        return result, agent, context

    def test_unknown_retrieves_caller_once_without_mutating_shared_context(self):
        second = dict(check_id='TEST_001', status='UNKNOWN', summary='Still unresolved',
                      evidence=[], limitations=[])
        result, agent, context = self.run_unknown([second])
        self.assertEqual(agent.call_count, 2)
        enriched = agent.call_args_list[1].args[1]['context']
        self.assertIn('!UNITY_EDITOR', enriched['files']['Game/Assets/Platform.cs'])
        self.assertNotIn('Game/Assets/Platform.cs', context['files'])
        self.assertEqual(result['review_retry']['initial_review']['status'], 'UNKNOWN')
        self.assertEqual(result['status'], 'UNKNOWN')

    def test_retry_fail_still_requires_verification(self):
        from validator.runner import run_check
        build, finding = self.setup_finding()
        first = dict(finding, status='UNKNOWN', evidence=[], summary='Factory caller missing')
        context = dict(files={'Game/Assets/Factory.cs': 'class Factory {}'}, limitations=[])
        with patch('validator.runner.invoke', side_effect=[first, finding,
                   dict(verdict='REJECTED', summary='Editor guarded', evidence=[])]) as agent:
            result = run_check(dict(id='TEST_001', severity='high', executor='agent'),
                               build, context, ['fixture'], 30, time.monotonic() + 60)
        self.assertEqual([c.args[1]['phase'] for c in agent.call_args_list], ['review', 'review', 'verify'])
        self.assertFalse(result['verified'])
        self.assertEqual(result['status'], 'UNKNOWN')

    def test_no_new_source_skips_second_call(self):
        from validator.runner import run_check
        build, finding = self.setup_finding()
        first = dict(finding, status='UNKNOWN', evidence=[], summary='Unresolved')
        with patch('validator.runner.invoke', return_value=first) as agent:
            result = run_check(dict(id='TEST_001', severity='high', executor='agent'), build,
                               dict(files={'readme.md': 'text'}, limitations=[]),
                               ['fixture'], 30, time.monotonic() + 60)
        self.assertEqual(agent.call_count, 1)
        self.assertEqual(result['status'], 'UNKNOWN')

    def test_retry_timeout_retains_initial_review_and_retrieval(self):
        result, agent, _ = self.run_unknown([subprocess.TimeoutExpired('fixture', 1)])
        self.assertEqual(agent.call_count, 2)
        self.assertEqual(result['execution_status'], 'TIMEOUT')
        self.assertFalse(result['verified'])
        self.assertIn('review_retry', result['candidate'])

    def test_missing_named_script_is_prioritized_over_unrelated_changes(self):
        from validator.review_context import collect
        build, finding = self.setup_finding()
        context = dict(files={'readme.md': 'text'}, changed_files=[
            'Game/Assets/AAA.cs', 'Game/Assets/Factory.cs'], limitations=[])
        review = dict(finding, status='UNKNOWN', evidence=[], summary='Factory.Create caller missing')
        extra = collect(build, review, context, time.monotonic() + 30)
        self.assertEqual(extra['seed_files'][0], 'Game/Assets/Factory.cs')
        self.assertEqual(extra['seed_files'], ['Game/Assets/Factory.cs'])
        self.assertIn('!UNITY_EDITOR', extra['files']['Game/Assets/Platform.cs'])

    def test_invalid_initial_response_does_not_trigger_retrieval(self):
        from validator.runner import run_check
        build, _ = self.setup_finding()
        with patch('validator.runner.invoke', return_value={}) as agent, patch(
                'validator.review_context.collect') as retrieve:
            result = run_check(dict(id='TEST_001', severity='high', executor='agent'), build,
                               dict(files={'readme.md': 'text'}, limitations=[]),
                               ['fixture'], 30, time.monotonic() + 60)
        self.assertEqual(agent.call_count, 1)
        retrieve.assert_not_called()
        self.assertEqual(result['execution_status'], 'ERROR')
