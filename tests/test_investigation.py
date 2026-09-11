import time
from unittest.mock import patch
from test_lifecycle import RepoCase


class InvestigationTests(RepoCase):
    def test_frozen_nested_configuration_and_xml(self):
        from validator.investigation import retrieve
        build, _, context, _ = self.setup_context()
        context['unity_project_prefix'] = 'Game/'
        paths = ['Game/ProjectSettings/ProjectSettings.asset',
                 'Game/Assets/Plugins/Android/AndroidManifest.xml',
                 'Game/Packages/plugin/Dependencies.xml']
        for path in paths:
            self.commit(path, 'applicationIdentifier: committed\n')
        build['target_sha'] = self.git('rev-parse', 'HEAD')
        for path in paths:
            (self.repo / path).write_text('working tree replacement')
            for kind in ('read', 'find', 'read_lines'):
                output = retrieve(build, context, dict(kind=kind, path=path, query='applicationIdentifier',
                                  snapshot='target', start_line=1, end_line=1), time.monotonic()+20)
                source = output['source'] if kind == 'read' else output['excerpts'][0]['source']
                self.assertIn('committed', source)
                self.assertNotIn('replacement', source)

    def test_missing_config_reports_snapshot_absence_without_disk_fallback(self):
        from validator.investigation import retrieve
        build, _, context, _ = self.setup_context()
        path = 'Assets/Plugins/Android/AndroidManifest.xml'
        disk = self.repo / path
        disk.parent.mkdir(parents=True)
        disk.write_text('uncommitted manifest')
        with self.assertRaisesRegex(ValueError, 'not present in.*snapshot'):
            retrieve(build, context, dict(kind='read',path=path,query='',snapshot='target'), time.monotonic()+20)

    def test_configuration_access_remains_scoped(self):
        from validator.investigation import retrieve
        build, _, context, _ = self.setup_context()
        context['unity_project_prefix'] = 'Game/'
        for path in ('ProjectSettings/ProjectSettings.asset', 'Game/UserSettings/Editor.asset',
                     'Game/Library/AndroidManifest.xml', 'Game/ProjectSettings/../secret.xml',
                     'Game/Assets/signing.keystore', 'Game/ProjectSettings/script.cs'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                retrieve(build, context, dict(kind='read',path=path,query='',snapshot='target'), time.monotonic()+20)

    def test_scoped_pass_keeps_runtime_limitations_in_coverage(self):
        from validator.investigation import investigate
        build, check, context, evidence = self.setup_context()
        response = dict(action='finish',requests=[],findings=[],status='PASS',summary='No defect in inspected method',
                        evidence=evidence,limitations=['No device test executed.'])
        with patch('validator.investigation.invoke',return_value=response):
            result = investigate(check,build,context,['fake'],20,time.monotonic()+30)
        self.assertEqual(result['review_outcome'],'NO_FINDINGS_IN_REVIEWED_SCOPE')
        self.assertEqual(result['investigation']['stop_reason'],'agent_finished')
        self.assertIn('No device test executed.',result['coverage']['limitations'])
        self.assertFalse(result['verified'])

    def test_literal_search_accepts_declaration_text(self):
        from validator.investigation import retrieve
        build, _, context, _ = self.setup_context()
        result = retrieve(build, context, dict(kind='search',path='',query='class Reward',snapshot='target'),time.monotonic()+20)
        self.assertIn('Assets/Scripts/Ads/Reward.cs', result['paths'])

    def test_configured_round_limit_and_budget_reserve(self):
        from validator.investigation import investigate
        build, check, context, _ = self.setup_context()
        context['project_config'] = dict(investigation=dict(max_rounds=2,verify_reserve_seconds=15))
        response = dict(action='retrieve', requests=[dict(kind='search',path='',query='Reward',snapshot='target')],
                        findings=[],status='UNKNOWN',summary='Read more',evidence=[],limitations=[])
        with patch('validator.investigation.invoke',return_value=response) as agent:
            result = investigate(check,build,context,['fake'],120,time.monotonic()+60)
        self.assertEqual(agent.call_count,2)
        self.assertEqual(result['investigation']['stop_reason'],'round_limit')
        self.assertEqual(result['investigation']['verify_reserve_seconds'],15)
        self.assertLessEqual(agent.call_args_list[0].args[2],45)
        self.assertEqual(result['review_outcome'],'UNRESOLVED')

    def setup_context(self):
        build = dict(repo=str(self.repo), baseline_sha=self.a, target_sha=self.a,
                     build_id='x', branch='main', profile='test')
        path = 'Assets/Scripts/Ads/Reward.cs'
        context = dict(files={path:'class Reward {}'}, changed_files=[path], limitations=[], diff='')
        check = dict(id='IMPACT_001', severity='high', executor='investigation')
        evidence = [dict(sha=self.a, file=path, line=1, reason='test source')]
        return build, check, context, evidence

    def test_findings_are_verified_separately(self):
        from validator.investigation import investigate
        build, check, context, evidence = self.setup_context()
        findings = [dict(check_id=check['id'], status='FAIL', summary='Finding '+str(i),
                         evidence=evidence, limitations=[]) for i in range(2)]
        response = dict(action='finish', requests=[], findings=findings, status='FAIL',
                        summary='Two hypotheses', evidence=evidence, limitations=[])
        def verify(command, request, timeout):
            self.assertEqual(request['phase'], 'verify')
            return dict(verdict='CONFIRMED' if request['finding']['summary'].endswith('0') else 'REJECTED',
                        evidence=evidence, summary='Fixture verification')
        with patch('validator.investigation.invoke', return_value=response), patch('validator.runner.invoke', side_effect=verify) as verifier:
            result = investigate(check, build, context, ['fake'], 20, time.monotonic()+30)
        self.assertEqual(verifier.call_count, 2)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual([f['verified'] for f in result['investigation']['findings']], [True, False])

    def test_round_cap_and_repeated_request_do_not_loop(self):
        from validator.investigation import investigate
        build, check, context, _ = self.setup_context()
        response = dict(action='retrieve', requests=[dict(kind='search', path='', query='Reward', snapshot='target')],
                        findings=[], status='UNKNOWN', summary='Find callers', evidence=[], limitations=[])
        with patch('validator.investigation.invoke', return_value=response) as agent:
            result = investigate(check, build, context, ['fake'], 20, time.monotonic()+30)
        self.assertEqual(agent.call_count, 6)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertTrue(any('Repeated' in x for x in result['limitations']))

    def test_tool_failure_cannot_become_pass(self):
        from validator.investigation import investigate
        build, check, context, evidence = self.setup_context()
        bad = dict(action='retrieve', requests=[dict(kind='read', path='../escape.cs', query='', snapshot='target')],
                   findings=[], status='UNKNOWN', summary='Read', evidence=[], limitations=[])
        finish = dict(action='finish', requests=[], findings=[], status='PASS', summary='Done', evidence=evidence, limitations=[])
        with patch('validator.investigation.invoke', side_effect=[bad,finish]):
            result = investigate(check, build, context, ['fake'], 20, time.monotonic()+30)
        self.assertEqual(result['status'], 'UNKNOWN')

    def test_graph_uses_frozen_snapshot_and_bounded_deadline(self):
        from validator.investigation import retrieve
        build, _, context, _ = self.setup_context()
        context['investigation_graph'] = dict(cache=str(self.root/'cache'), roots=['Assets','Packages'])
        with patch('validator.unity_mcp.collect', return_value=dict(status='COMPLETED',limitations=[])) as graph:
            retrieve(build, context, dict(kind='graph',path='Assets/Scripts/Ads/Reward.cs',query='',snapshot='baseline'),time.monotonic()+60)
        self.assertEqual(graph.call_args.args[0]['target_sha'], self.a)
        self.assertIsNone(graph.call_args.args[0]['baseline_sha'])
        self.assertLessEqual(graph.call_args.args[-1],time.monotonic()+20)

    def test_agent_reads_frozen_source_then_finishes(self):
        from validator.investigation import investigate
        sha = self.commit('Assets/Other.cs', 'class Other { int value; }')
        (self.repo / 'Assets/Other.cs').write_text('dirty')
        build = dict(repo=str(self.repo), baseline_sha=self.a, target_sha=sha,
                     build_id='x', branch='main', profile='test')
        check = dict(id='IMPACT_001', severity='high', executor='investigation')
        context = dict(files={}, changed_files=['Assets/Other.cs'], limitations=[], diff='')
        first = dict(action='retrieve', requests=[dict(kind='read', path='Assets/Other.cs', query='', snapshot='target')],
                     findings=[], status='UNKNOWN', summary='Read implementation', evidence=[], limitations=[])
        def second(command, request, timeout):
            self.assertIn('int value', request['context']['files']['Assets/Other.cs'])
            self.assertNotIn('dirty', str(request))
            return dict(action='finish', requests=[], findings=[], status='UNKNOWN', summary='Missing caller', evidence=[], limitations=[])
        with patch('validator.investigation.invoke', side_effect=lambda c,r,t: first if r['round']==1 else second(c,r,t)):
            result = investigate(check, build, context, ['fake'], 20, time.monotonic()+30)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(len(result['investigation']['rounds']), 2)
        self.assertEqual(context['files'], {})

    def test_retrieval_rejects_escape_and_keeps_baseline_separate(self):
        from validator.investigation import retrieve
        build = dict(repo=str(self.repo), baseline_sha=self.a, target_sha=self.a)
        with self.assertRaises(ValueError):
            retrieve(build, {}, dict(kind='read', path='../secrets', snapshot='target', query=''), time.monotonic()+20)
        result = retrieve(build, {}, dict(kind='read', path='Assets/Scripts/Ads/Reward.cs', snapshot='baseline', query=''), time.monotonic()+20)
        self.assertEqual(result['sha'], self.a)
        self.assertEqual(result['snapshot'], 'baseline')
