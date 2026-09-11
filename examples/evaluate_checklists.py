"""Evaluate real checklist agents on retained Git fixtures, without touching a game."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from examples.checklist_cases import CASES, DEFAULT_CASES, load_cases
from validator.project import load_config
import yaml
from validator.runner import analyze
from validator.store import Store


def score(expected, report):
    checks = {c['check_id']: c for c in report.get('checks', [])}
    rows = []
    for check_id, label in expected.items():
        actual = checks.get(check_id, {})
        matched = (actual.get('status') == label and actual.get('execution_status') == 'COMPLETED'
                   and (label != 'FAIL' or actual.get('verified') is True))
        rows.append(dict(check_id=check_id, expected=label, actual=actual.get('status', 'MISSING'),
                         verified=actual.get('verified', False), matched=matched,
                         execution_status=actual.get('execution_status', 'MISSING'),
                         summary=actual.get('summary', '')))
    return rows


def prepare(directory, name, cases=None):
    case = (cases if cases is not None else CASES)[name]
    expected = case['expected']
    case_dir = directory / ('case-' + uuid.uuid4().hex)
    repo = case_dir / 'repo'
    repo.mkdir(parents=True)
    config = case_dir / 'project.yaml'
    config.write_text(yaml.safe_dump(case['project']), encoding='utf-8')
    load_config(config)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
    git('init', '-b', 'main')
    git('config', 'user.name', 'Local Checklist Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    # Keep labels and case names outside Git and outside the agent request.
    for filename, source in case.get('baseline_files',
            {p: '// Feature not implemented yet.\n' for p in case['files']}).items():
        path = repo / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    git('add', '.')
    git('commit', '-qm', 'Baseline')
    store = Store(case_dir / 'state.db')
    store.order('baseline', str(repo), 'main', 'fixture', git('rev-parse', 'HEAD'))
    store.confirm('baseline')  # Synthetic baseline, not a real Unity build confirmation.
    for filename, source in case['files'].items():
        path = repo / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    git('add', '.')
    git('commit', '-qm', 'Implement feature')
    store.order('target', str(repo), 'main', 'fixture', git('rev-parse', 'HEAD'))
    return store, config, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-only', action='store_true', help='Create fixtures without calling any model')
    mode.add_argument('--backend', choices=['codex', 'opencode'], help='Live run consumes provider usage')
    parser.add_argument('--model')
    parser.add_argument('--case', action='append', help='Case ID from YAML; repeat to select several')
    parser.add_argument('--cases-dir', default=str(DEFAULT_CASES))
    parser.add_argument('--workflows', default=str(ROOT / 'workflows'))
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--budget', type=float, default=600, help='Per-case total budget in seconds')
    args = parser.parse_args()
    if not 0 < args.timeout <= 600 or not 0 < args.budget <= 3600:
        parser.error('timeout must be (0,600], budget (0,3600]')
    if args.model and not args.backend:
        parser.error('--model requires --backend')
    cases = load_cases(args.cases_dir)
    if set(args.case or []) - set(cases):
        parser.error('Unknown case ID')
    output = ROOT / '.validator' / 'checklist-evals'
    output.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='run-', dir=output))
    summary = dict(directory=str(directory), backend=args.backend, model=args.model,
                   prepare_only=args.prepare_only, cases=[], synthetic=True)
    for name in dict.fromkeys(args.case or cases):
        print('Preparing ' + name if args.prepare_only else 'Evaluating ' + name, file=sys.stderr, flush=True)
        store, config, expected = prepare(directory, name, cases)
        item = dict(case=name, db=str(store.path), config=str(config))
        if args.prepare_only:
            item['expected'] = expected
        else:
            try:
                result = analyze(store, 'target', Path(args.workflows), backend=args.backend,
                                 model=args.model, timeout=args.timeout, budget=args.budget,
                                 project_config=config, fixture_execution=cases[name].get('execution'))
                item['checks'] = score(expected, result['report'])
                report_path = store.path.parent / 'report.json'
                report_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
                item['report_path'] = str(report_path)
            except Exception as exc:
                item.update(error=str(exc), checks=score(expected, {}))
        summary['cases'].append(item)
        (directory / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    rows = [r for case in summary['cases'] for r in case.get('checks', [])]
    summary.update(evaluated_checks=len(rows), matched_checks=sum(r['matched'] for r in rows))
    (directory / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if args.prepare_only or all(r['matched'] for r in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
