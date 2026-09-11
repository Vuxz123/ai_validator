import shutil
from contextlib import closing
import sqlite3
import subprocess
import time
import unittest

from test_lifecycle import RepoCase, ROOT


SHELL = shutil.which('pwsh') or shutil.which('powershell')


@unittest.skipUnless(SHELL, 'PowerShell is required for the Windows pipeline example')
class PipelineTests(RepoCase):
    def run_build(self, exit_code, agent_command=None):
        script = self.root / 'build.ps1'
        script.write_text("param([string]$TargetSha)\n"
                          "[IO.File]::WriteAllText((Join-Path $PWD 'built-sha.txt'), $TargetSha)\n"
                          f'exit {exit_code}\n')
        command = [SHELL, '-NoProfile', '-File', str(ROOT / 'examples/build-local.ps1'),
                   '-Repo', str(self.repo), '-Branch', 'main', '-BuildScript', str(script),
                   '-DatabasePath', str(self.db)]
        if agent_command:
            command += ['-AgentCommand', agent_command]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
        self.assertEqual((self.repo / 'built-sha.txt').read_text(), self.a)
        for _ in range(40):
            with closing(sqlite3.connect(self.db)) as db:
                row = db.execute('SELECT confirmed_at, analysis_status FROM builds').fetchone()
            if row and row[1] in ('COMPLETED', 'FAILED'):
                return row
            time.sleep(0.1)
        self.fail('Worker did not finish')

    def test_success_confirms_even_if_analysis_configuration_fails(self):
        row = self.run_build(0, str(self.root / 'missing-agent.json'))
        self.assertIsNotNone(row[0])
        self.assertEqual(row[1], 'FAILED')

    def test_failed_build_keeps_exit_code_and_does_not_confirm(self):
        row = self.run_build(7)
        self.assertIsNone(row[0])
