import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from test_lifecycle import ROOT


REQUEST = {'phase': 'review', 'check': {'id': 'TEST_001'}, 'context': {}, 'build': {}}


class BackendTests(unittest.TestCase):
    def test_timeout_stops_spawned_child(self):
        from validator.agent import invoke
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'child.txt'
            with patch.dict(os.environ, {'VALIDATOR_TEST_MARKER': str(marker)}):
                with self.assertRaises(subprocess.TimeoutExpired):
                    invoke(self.backend('codex', 'child_timeout'), REQUEST, 0.8)
            self.assertTrue(Path(str(marker) + '.started').exists())
            time.sleep(2.2)
            self.assertFalse(marker.exists(), 'Timed-out CLI left its child process running')

    def test_malformed_completion_event_is_a_protocol_error(self):
        from validator.backends import parse_opencode
        with self.assertRaises(ValueError):
            parse_opencode(b'{"type":"step_finish","part":null}')

    def backend(self, kind, mode='ok'):
        from validator.backends import Backend
        return Backend(kind, 'test/model', [sys.executable, str(ROOT / 'tests/fixture_cli.py'), kind, mode])

    def test_both_backends_review_and_verify(self):
        from validator.agent import invoke
        for kind in ('codex', 'opencode'):
            with self.subTest(kind=kind):
                self.assertEqual(invoke(self.backend(kind), REQUEST, 5)['status'], 'UNKNOWN')
                self.assertEqual(invoke(self.backend(kind), {**REQUEST, 'phase': 'verify'}, 5)['verdict'],
                                 'CONFIRMED')

    def test_cli_errors_and_incomplete_stream_are_not_results(self):
        from validator.agent import invoke
        for kind, mode in [('codex', 'invalid'), ('codex', 'exit'),
                           ('opencode', 'error_event'), ('opencode', 'incomplete'), ('opencode', 'exit')]:
            with self.subTest(kind=kind, mode=mode), self.assertRaises(ValueError):
                invoke(self.backend(kind, mode), REQUEST, 5)

    def test_cli_timeout(self):
        from validator.agent import invoke
        for kind in ('codex', 'opencode'):
            with self.subTest(kind=kind), self.assertRaises(subprocess.TimeoutExpired):
                invoke(self.backend(kind, 'timeout'), REQUEST, 0.1)

    def test_windows_npm_shims_are_resolved_without_shell(self):
        from validator.backends import resolve_executable
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = root / 'node_modules/@openai/codex/bin/codex.js'
            opencode = root / 'node_modules/opencode-ai/bin/opencode.exe'
            for file in (codex, opencode):
                file.parent.mkdir(parents=True)
                file.touch()
            for kind, target in [('codex', codex), ('opencode', opencode)]:
                shim = root / (kind + '.cmd')
                shim.touch()
                with patch('validator.backends.shutil.which', return_value=sys.executable):
                    command = resolve_executable(kind, str(shim))
                self.assertEqual(command[-1], str(target))
                self.assertNotIn(str(shim), command)

    def test_worker_forwards_backend_model_and_executable(self):
        from argparse import Namespace
        from validator.__main__ import start_worker
        from validator.store import Store
        with tempfile.TemporaryDirectory() as directory:
            args = Namespace(workflows=str(ROOT / 'workflows'), timeout=10, budget=20,
                             agent_command=None, backend='opencode', model='test/model',
                             agent_executable=sys.executable, project_config=str(Path(directory) / 'project.yaml'))
            with patch('validator.__main__.subprocess.Popen') as popen:
                start_worker(Store(Path(directory) / 'state.db'), 'test', args)
            command = popen.call_args.args[0]
            self.assertIn('--backend', command)
            self.assertEqual(command[command.index('--project-config') + 1],
                             str(Path(directory) / 'project.yaml'))
            self.assertEqual(command[command.index('--backend') + 1], 'opencode')
            self.assertEqual(command[command.index('--model') + 1], 'test/model')
            self.assertEqual(command[command.index('--agent-executable') + 1], sys.executable)
