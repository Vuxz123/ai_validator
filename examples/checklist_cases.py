"""Load editable evaluation data; expected labels stay outside agent input."""
from pathlib import Path
import re
import yaml
from validator.workflows import UniqueLoader, fields, require
from validator.project import relative

DEFAULT_CASES = Path(__file__).resolve().parent / 'checklist_cases'


def load_cases(folder=DEFAULT_CASES):
    cases = {}
    for path in sorted(Path(folder).glob('*.yaml')):
        require(path.stat().st_size <= 1000000, 'Case YAML exceeds 1 MB')
        case = yaml.load(path.read_text(encoding='utf-8-sig'), Loader=UniqueLoader)
        fields(case, {'id', 'project', 'files', 'expected', 'execution'}, {'id', 'project', 'files', 'expected'})
        if 'execution' in case:
            fields(case['execution'], {'entrypoint', 'assumption'}, {'entrypoint', 'assumption'})
            require(all(isinstance(v, str) and v.strip() and len(v) <= 2000
                        for v in case['execution'].values()), 'Invalid execution assumption')
        name = case['id']
        require(isinstance(name, str) and re.fullmatch(r'[a-z][a-z0-9_]*', name), 'Invalid case ID')
        require(name not in cases, 'Duplicate case ID')
        require(isinstance(case['project'], dict), 'Case project must be a mapping')
        files = case['files']
        require(isinstance(files, dict) and 0 < len(files) <= 100, 'Case requires 1..100 source files')
        for filename, text in files.items():
            require(relative(filename) and all(part not in ('', '.') and not part.lower().startswith('.git')
                    for part in filename.split('/')) and isinstance(text, str), 'Invalid fixture file')
        require(isinstance(case['expected'], dict) and bool(case['expected']), 'Missing expected labels')
        for check_id, label in case['expected'].items():
            require(re.fullmatch(r'[A-Z][A-Z0-9_]*', check_id) and label in
                    ('PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE'), 'Invalid expected label')
        cases[name] = case
    require(bool(cases), 'No case YAML found')
    return cases


CASES = load_cases()
