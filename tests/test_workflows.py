import tempfile
from pathlib import Path
import unittest

from validator.workflows import load_workflows, select_workflows


VALID = '''id: example
version: 1
triggers:
  changed_paths: [Assets/Scripts/Ads/**]
checks:
  - id: EXAMPLE_001
    description: Check example.
    executor: agent
    severity: high
    context: [changed_code]
    evidence_required: [Call path]
'''


class WorkflowTests(unittest.TestCase):
    def test_ai_guidance_without_legacy_description(self):
        content = VALID.replace('description: Check example.', '''objective: Check reward correctness.
    instructions: [Trace callbacks, Inspect guards]
    context_requests: [Find reward callers]
    verdicts:
      pass: All paths guarded.
      fail: Reachable invalid reward.
      unknown: Missing callback implementation.''').replace('    context: [changed_code]\n', '')
        check = self.load(content)[0]['checks'][0]
        self.assertEqual(check['objective'], 'Check reward correctness.')
        self.assertEqual(check['instructions'][0], 'Trace callbacks')
        self.assertEqual(check['context'], ['changed_code', 'diff'])
        with self.assertRaises(ValueError):
            self.load(content.replace('pass: All paths guarded.', 'maybe: All paths guarded.'))

    def load(self, content):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'example.yaml').write_text(content, encoding='utf-8')
            return load_workflows(directory)

    def test_rejects_unknown_provider_executor_and_duplicate_keys(self):
        for content in (VALID.replace('changed_code', 'reward_callers'),
                        VALID.replace('executor: agent', 'executor: shell'),
                        VALID.replace('version: 1', 'version: 1\nversion: 2')):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.load(content)

    def test_path_routing_includes_nested_files(self):
        definitions = self.load(VALID)
        self.assertEqual(len(select_workflows(definitions, ['Assets/Scripts/Ads/Sub/Reward.cs'])), 1)
        self.assertEqual(select_workflows(definitions, ['Assets/Scripts/Other.cs']), [])
