import time
from unittest.mock import patch
from test_lifecycle import RepoCase


class VerificationContextTests(RepoCase):
    def test_comments_and_strings_do_not_supply_type_names(self):
        from validator.verification_context import collect
        build, finding = self.setup_finding()
        build['target_sha'] = self.commit('Game/Assets/Factory.cs', '''// class must never be searched
/* interface from documentation */
class Factory { string s = "class can"; string v = @"struct bogus";
string raw = """class nope"""; }
''')
        extra = collect(build, finding, time.monotonic() + 30)
        self.assertEqual(extra['search_names'], ['Factory'])
        self.assertIn('Game/Assets/Platform.cs', extra['files'])

    def test_each_seed_gets_callers_despite_noisy_other_seed(self):
        from validator.verification_context import collect
        build, finding = self.setup_finding()
        self.commit('Game/Assets/ANoisy.cs', 'class ANoisy {}')
        for i in range(6):
            build['target_sha'] = self.commit('Game/Assets/ANoise%d.cs' % i,
                                             'class Noise%d { ANoisy field; }' % i)
        finding['evidence'].insert(0, dict(file='Game/Assets/ANoisy.cs'))
        extra = collect(build, finding, time.monotonic() + 30, max_files=6)
        self.assertIn('Game/Assets/Platform.cs', extra['files'])
        self.assertFalse(extra['complete'])

    def test_truncated_caller_record_is_never_read_as_source(self):
        from validator.verification_context import collect
        build, finding = self.setup_finding()
        prefix = (build['target_sha'] + ':').encode()
        # Last record ends at SHA:, which previously became the empty path.
        complete = prefix + b'Game/Assets/Platform.cs\0'
        raw = complete + b'x' * (32000 - len(complete) - len(prefix) - 1) + b'\0' + prefix + b'x'
        def read(repo, *args, **kwargs):
            if args[0] == 'grep':
                return raw
            self.assertNotEqual(args[1], build['target_sha'] + ':')
            return b'class Factory {}'
        with patch('validator.verification_context.git', side_effect=read):
            extra = collect(build, finding, time.monotonic() + 30)
        self.assertNotIn('', extra['files'])
        self.assertEqual(extra['caller_files'], ['Game/Assets/Platform.cs'])
        self.assertFalse(extra['complete'])

    def setup_finding(self):
        self.commit('Game/Assets/Factory.cs', 'class Factory { public static void Create() {} }\n')
        sha = self.commit('Game/Assets/Platform.cs', '#if UNITY_ANDROID && !UNITY_EDITOR\nclass Platform { void Go() { Factory.Create(); } }\n#endif\n')
        build = dict(repo=str(self.repo), target_sha=sha, baseline_sha=self.a,
                     build_id='test', branch='main', profile='android')
        finding = dict(check_id='TEST_001', status='FAIL', summary='Editor reachable', limitations=[],
                       evidence=[dict(sha=sha, file='Game/Assets/Factory.cs', line=1, reason='Factory call')])
        return build, finding

    def test_reads_unchanged_caller_and_guards_from_target(self):
        from validator.verification_context import collect
        build, finding = self.setup_finding()
        (self.repo / 'Game/Assets/Platform.cs').write_text('dirty')
        result = collect(build, finding, time.monotonic() + 30)
        self.assertTrue(result['complete'])
        self.assertIn('!UNITY_EDITOR', result['files']['Game/Assets/Platform.cs'])

    def test_over_budget_caller_cannot_confirm(self):
        from validator.verification_context import collect
        build, finding = self.setup_finding()
        result = collect(build, finding, time.monotonic() + 30, max_bytes=60)
        self.assertFalse(result['complete'])

    def test_verify_receives_guards_and_rejects_candidate(self):
        from validator.runner import run_check
        build, finding = self.setup_finding()
        context = {'files': {'Game/Assets/Factory.cs': 'class Factory {}'}, 'limitations': []}
        def agent(command, request, timeout):
            if request['phase'] == 'review':
                return finding
            self.assertIn('!UNITY_EDITOR', request['context']['files']['Game/Assets/Platform.cs'])
            return dict(verdict='REJECTED', summary='Editor excluded at caller', evidence=[
                dict(sha=build['target_sha'], file='Game/Assets/Platform.cs', line=1, reason='Editor guard')])
        with patch('validator.runner.invoke', side_effect=agent):
            result = run_check(dict(id='TEST_001', severity='high', executor='agent'), build, context,
                               ['fixture'], 30, time.monotonic() + 60)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertFalse(result['verified'])
        self.assertEqual(result['verification']['verdict'], 'REJECTED')

    def test_incomplete_context_overrides_model_confirmation(self):
        from validator.runner import run_check
        build, finding = self.setup_finding()
        context = {'files': {'Game/Assets/Factory.cs': 'class Factory {}'}, 'limitations': []}
        verification = dict(verdict='CONFIRMED', summary='Model agrees', evidence=finding['evidence'])
        with patch('validator.runner.invoke', side_effect=[finding, verification]), patch(
                'validator.verification_context.collect', return_value=dict(
                    files={}, complete=False, caller_files=[], limitations=['Caller omitted'], sha=build['target_sha'])):
            result = run_check(dict(id='TEST_001', severity='high', executor='agent'), build, context,
                               ['fixture'], 30, time.monotonic() + 60)
        self.assertFalse(result['verified'])
        self.assertEqual(result['status'], 'UNKNOWN')
