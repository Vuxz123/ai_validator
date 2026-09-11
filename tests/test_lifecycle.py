import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.db = self.root / 'state.db'
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Validator Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.a = self.commit('Assets/Scripts/Ads/Reward.cs', 'class Reward {}\n')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()

    def commit(self, path, content):
        file = self.repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-qm', 'Update fixture')
        return self.git('rev-parse', 'HEAD')

    def cli(self, *args, success=True):
        result = subprocess.run(
            [sys.executable, '-m', 'validator', '--db', str(self.db), *args],
            cwd=ROOT, text=True, capture_output=True,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result

    def order(self, build_id, target='HEAD', profile='android'):
        return self.cli('order', '--repo', str(self.repo), '--branch', 'main',
                        '--profile', profile, '--target', target,
                        '--build-id', build_id, '--no-start')


class LifecycleTests(RepoCase):
    def test_freezes_baseline_and_target_even_when_head_changes(self):
        self.order('a')
        self.cli('confirm', 'a')
        b = self.commit('Assets/Scripts/Ads/Reward.cs', 'class Reward { int x; }\n')
        ordered = self.order('b')
        self.commit('unrelated.txt', 'new head')
        self.assertEqual(ordered['baseline_sha'], self.a)
        self.assertEqual(ordered['target_sha'], b)
        self.cli('confirm', 'b')
        self.assertEqual(self.order('c')['baseline_sha'], b)

    def test_unconfirmed_build_does_not_advance_baseline(self):
        self.order('a')
        self.cli('confirm', 'a')
        self.commit('x.txt', 'failed build')
        self.order('failed')
        self.assertEqual(self.order('next')['baseline_sha'], self.a)

    def test_confirmation_is_idempotent_and_old_order_cannot_rewind(self):
        self.order('old')
        b = self.commit('b.txt', 'new')
        self.order('new')
        self.cli('confirm', 'new')
        self.cli('confirm', 'old')
        self.cli('confirm', 'new')
        self.assertEqual(self.order('next')['baseline_sha'], b)

    def test_profile_isolation_and_first_build(self):
        self.assertIsNone(self.order('a')['baseline_sha'])
        self.cli('confirm', 'a')
        self.assertIsNone(self.order('ios', profile='ios')['baseline_sha'])

    def test_order_retry_and_conflicting_id(self):
        original = self.order('a', self.a)
        self.assertEqual(self.order('a', self.a)['sequence'], original['sequence'])
        self.commit('new.txt', 'new')
        self.cli('order', '--repo', str(self.repo), '--branch', 'main',
                 '--target', 'HEAD', '--profile', 'android', '--build-id', 'a',
                 '--no-start', success=False)


if __name__ == '__main__':
    unittest.main()
