import time
from test_lifecycle import RepoCase
from validator.investigation import retrieve
from validator.agent import validate_evidence


class SourceWindowTests(RepoCase):
    def test_large_prefab_find_and_original_line_evidence(self):
        path = 'Assets/Large.prefab'
        text = ('padding: ' + 'x'*100 + '\n')*1000 + '  autoAuthenticate: 1\n' + 'tail: 0\n'*50
        sha = self.commit(path, text)
        (self.repo/path).write_text('dirty')
        build = dict(repo=str(self.repo), target_sha=sha, baseline_sha=self.a)
        result = retrieve(build, {}, dict(kind='find',path=path,query='autoAuthenticate',snapshot='target'),time.monotonic()+20)
        self.assertFalse(result['truncated'])
        self.assertTrue(result['partial'])
        self.assertIn('autoAuthenticate: 1', result['excerpts'][0]['source'])
        context = dict(files={},source_excerpts={path:result['excerpts']})
        evidence = dict(sha=sha,file=path,line=1001,reason='Serialized value')
        validate_evidence([evidence],build,context,True)
        for line in (1, 1050):
            with self.assertRaises(ValueError):
                validate_evidence([{**evidence,'line':line}],build,context,True)
        with self.assertRaises(ValueError):
            validate_evidence([{**evidence,'sha':self.a}],build,context,True)

    def test_range_bound_and_no_match(self):
        path = 'Assets/Scripts/Ads/Reward.cs'
        build = dict(repo=str(self.repo),target_sha=self.a,baseline_sha=self.a)
        request = dict(kind='read_lines',path=path,query='',snapshot='target',start_line=1,end_line=400)
        result = retrieve(build,{},request,time.monotonic()+20)
        self.assertEqual(result['excerpts'][0]['start_line'],1)
        self.assertEqual(result['excerpts'][0]['end_line'],1)
        with self.assertRaises(ValueError):
            retrieve(build,{},dict(request,end_line=401),time.monotonic()+20)
        empty = retrieve(build,{},dict(request,kind='find',query='not_present'),time.monotonic()+20)
        self.assertEqual(empty['excerpts'],[])
