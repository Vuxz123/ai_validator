import hashlib
import json
from pathlib import Path
import tempfile
import unittest


class RelatedContextTests(unittest.TestCase):
    def test_snapshot_binding_and_bounded_relations(self):
        from validator.related_context import get_related_context
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = {'nodes': [{'id': 'a', 'type': 'Script', 'file_path': 'Assets\\A.cs'},
                               {'id': 'b', 'type': 'Script', 'file_path': 'Assets/B.cs'}],
                     'edges': [{'from': 'b', 'to': 'a', 'type': 'calls',
                                'sites': [{'file': 'Assets/B.cs', 'line': 3}]}]}
            path = root / 'graph.json'
            path.write_text(json.dumps(graph))
            manifest = root / 'snapshot.json'
            manifest.write_text(json.dumps({'sha': 'abc', 'graph_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}))
            result = get_related_context(path, manifest, 'abc', 'Assets/A.cs')
            self.assertEqual(len(result['edges']), 1)
            with self.assertRaises(ValueError):
                get_related_context(path, manifest, 'other', 'Assets/A.cs')
            path.write_text('{}')
            with self.assertRaises(ValueError):
                get_related_context(path, manifest, 'abc', 'Assets/A.cs')
