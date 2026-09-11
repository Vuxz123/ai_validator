import tempfile
import unittest
from pathlib import Path

from validator.workflows import load_workflows
from test_lifecycle import RepoCase


class ProjectConfigTests(unittest.TestCase):
    def test_same_rules_across_layouts(self):
        from validator.project import route
        rules = load_workflows(Path(__file__).resolve().parents[1] / 'workflows')
        for root, folder in [('.', 'Assets/Monetization'), ('Game', 'Assets/Studio/Ads')]:
            config = dict(unity_root=root, source_groups={'ads': [folder + '/**']},
                          rule_packs=['rewarded_ads'])
            prefix = '' if root == '.' else root + '/'
            result = route(rules, [prefix + folder + '/Reward.cs'], config)
            ads = next(r for r in result if r['workflow_id'] == 'rewarded_ads')
            self.assertEqual(ads['status'], 'SELECTED')
            self.assertEqual(ads['matched_paths'], [prefix + folder + '/Reward.cs'])

    def test_missing_mapping_is_not_no_match(self):
        from validator.project import route
        rules = load_workflows(Path(__file__).resolve().parents[1] / 'workflows')
        result = route(rules, ['Assets/Scripts/Ads/Reward.cs'],
                       dict(unity_root='.', source_groups={}, rule_packs=['rewarded_ads']))
        self.assertEqual(next(r for r in result if r['workflow_id'] == 'rewarded_ads')['status'],
                         'MISSING_MAPPING')
        self.assertEqual(next(r for r in result if r['workflow_id'] == 'code_impact')['status'], 'DISABLED')

    def test_config_rejects_escape_unknown_keys_and_empty_groups(self):
        from validator.project import load_config
        for content in ['unity_root: ../Game', 'unexpected: true', 'source_groups: {ads: []}',
                        'source_groups: {ads: [../outside/**]}', 'unity_root: C:/Game',
                        'investigation: {max_rounds: 99}',
                        'investigation: {verify_reserve_seconds: -1}']:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'project.yaml'
                path.write_text(content)
                with self.assertRaises(ValueError):
                    load_config(path)

    def test_ownership_does_not_guess(self):
        from validator.project import ownership
        config = dict(unity_root='Game', source_groups={'first_party': ['Assets/Own/**'],
                      'third_party': ['Assets/Vendor/**']})
        self.assertEqual(ownership('Game/Assets/Vendor/X.cs', config), 'third_party')
        self.assertEqual(ownership('Game/Assets/Other.cs', config), 'unknown')


class ProjectCliTests(RepoCase):
    def config(self, groups='  ads: [Assets/Studio/**]\n', packs='[rewarded_ads]'):
        path = self.root / 'project.yaml'
        path.write_text('version: 1\nunity_root: Game\nsource_groups:\n' + groups
                        + 'rule_packs: ' + packs + '\n')
        return str(path)

    def test_preview_matches_analysis_and_does_not_create_database(self):
        target = self.commit('Game/Assets/Studio/Reward.cs', 'class Reward { int changed; }')
        config = self.config()
        preview = self.cli('preview', '--repo', str(self.repo), '--baseline', self.a,
                           '--target', target, '--project-config', config)
        self.assertFalse(self.db.exists())
        self.order('base', self.a)
        self.cli('confirm', 'base')
        self.order('target', target)
        report = self.cli('analyze', 'target', '--project-config', config)['report']
        self.assertEqual(preview['routing'], report['routing'])
        self.assertIn('rewarded_ads', report['selected_workflows'])
        self.assertNotIn('code_impact', report['selected_workflows'])
        self.assertEqual(report['project_config']['unity_root'], 'Game')
        self.assertEqual(report['unity_project_prefix'], 'Game/')
        self.assertTrue(report['project_config_hash'])

    def test_missing_mapping_makes_report_incomplete_without_model(self):
        config = self.config('  first_party: [Assets/**]\n')
        self.order('base')
        self.cli('confirm', 'base')
        self.commit('Game/Assets/Other.cs', 'class Other {}')
        self.order('target')
        report = self.cli('analyze', 'target', '--project-config', config)['report']
        self.assertEqual(report['assessment'], 'INCOMPLETE')
        self.assertTrue(any('Missing mapping' in x for x in report['limitations']))

    def test_nested_texture_ownership_without_graph(self):
        self.order('base')
        self.cli('confirm', 'base')
        self.commit('Game/Assets/Vendor/icon.png', 'fixture')
        self.order('target')
        config = self.config('  third_party: [Assets/Vendor/**]\n', '[texture_metadata]')
        report = self.cli('analyze', 'target', '--project-config', config)['report']
        check = next(c for c in report['checks'] if c['check_id'] == 'TEXTURE_META_001')
        self.assertEqual(check['status'], 'FAIL')
        self.assertTrue(all(e['ownership'] == 'third_party' for e in check['source_ownership']))

    def test_unknown_pack_is_error(self):
        self.cli('preview', '--repo', str(self.repo), '--baseline', self.a,
                 '--project-config', self.config(packs='[typo]'), success=False)
