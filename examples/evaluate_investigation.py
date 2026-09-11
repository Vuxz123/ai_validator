"""Evaluate open investigation on synthetic Git changes; live backends consume usage."""
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import yaml
from examples.evaluate_checklists import prepare
from validator.project import relative
from validator.runner import analyze
from validator.workflows import UniqueLoader, fields, require

DEFAULT_CASES = ROOT / 'examples' / 'investigation_cases'


def load_cases(folder=DEFAULT_CASES):
    cases = {}
    for path in sorted(Path(folder).glob('*.yaml')):
        require(path.stat().st_size <= 1000000, 'Case exceeds 1 MB')
        case = yaml.load(path.read_text(encoding='utf-8-sig'), Loader=UniqueLoader)
        keys = {'id', 'project', 'baseline_files', 'files', 'execution', 'expected'}
        fields(case, keys, keys)
        name = case['id']
        require(isinstance(name, str) and re.fullmatch(r'[a-z][a-z0-9_]*', name)
                and name not in cases, 'Invalid or duplicate case ID')
        require(isinstance(case['project'], dict) and case['project'].get('rule_packs') == ['code_impact'],
                'Investigation cases must enable only code_impact')
        for key in ('baseline_files', 'files'):
            files = case[key]
            require(isinstance(files, dict) and 0 < len(files) <= 100, 'Requires 1..100 files')
            for filename, source in files.items():
                require(relative(filename) and all(p not in ('', '.') and not p.lower().startswith('.git')
                        for p in filename.split('/')) and isinstance(source, str), 'Invalid fixture file')
        fields(case['execution'], {'entrypoint', 'assumption'}, {'entrypoint', 'assumption'})
        require(all(isinstance(v, str) and v.strip() and len(v) <= 2000
                    for v in case['execution'].values()), 'Invalid execution premise')
        expected = case['expected']
        fields(expected, {'status', 'findings'}, {'status', 'findings'})
        require(expected['status'] in ('PASS', 'FAIL', 'UNKNOWN'), 'Invalid expected status')
        require(isinstance(expected['findings'], list) and len(expected['findings']) <= 5,
                'Invalid expected findings')
        require((expected['status'] == 'FAIL') == bool(expected['findings']), 'FAIL needs finding rubrics')
        for finding in expected['findings']:
            keys = {'file', 'start_line', 'end_line', 'ownership', 'summary_any'}
            fields(finding, keys, keys)
            require(finding['file'] in case['files'], 'Evidence anchor must be in target files')
            require(type(finding['start_line']) is int and type(finding['end_line']) is int
                    and 1 <= finding['start_line'] <= finding['end_line']
                    <= len(case['files'][finding['file']].splitlines()), 'Invalid evidence range')
            require(finding['ownership'] in ('first_party', 'third_party'), 'Invalid ownership')
            require(isinstance(finding['summary_any'], list) and finding['summary_any']
                    and all(isinstance(s, str) and s.strip() for s in finding['summary_any']), 'Missing mechanism terms')
        cases[name] = case
    require(bool(cases), 'No case YAML found')
    return cases


def matches(rubric, finding):
    return (finding.get('status') == 'FAIL' and finding.get('verified') is True
            and finding.get('execution_status') == 'COMPLETED'
            and any(e.get('file') == rubric['file'] and type(e.get('line')) is int
                    and rubric['start_line'] <= e['line'] <= rubric['end_line']
                    for e in finding.get('evidence', []))
            and any(o.get('file') == rubric['file'] and o.get('ownership') == rubric['ownership']
                    for o in finding.get('source_ownership', []))
            and any(term.casefold() in finding.get('summary', '').casefold()
                    for term in rubric['summary_any']))


def score(expected, check):
    findings = check.get('investigation', {}).get('findings', [])
    # Maximum one-to-one matching: duplicate findings cannot satisfy several rubrics.
    def assign(index, used):
        if index == len(expected['findings']):
            return []
        options = [assign(index+1, used)]
        for i, finding in enumerate(findings):
            if i not in used and matches(expected['findings'][index], finding):
                options.append([(index, i)] + assign(index+1, used | {i}))
        return max(options, key=len)
    pairs = assign(0, set())
    confirmed = sum(f.get('status') == 'FAIL' and f.get('verified') is True for f in findings)
    matched = (check.get('status') == expected['status'] and check.get('execution_status') == 'COMPLETED'
               and check.get('investigation', {}).get('stop_reason') in ('agent_finished', 'final_round_finished')
               and not any('error' in tool for tool in check.get('investigation_context', {}).get('tool_results', []))
               and len(pairs) == len(expected['findings']) and len(findings) == len(pairs)
               and (expected['status'] != 'FAIL' or check.get('verified') is True))
    return dict(expected=expected['status'], actual=check.get('status', 'MISSING'), matched=matched,
                execution_status=check.get('execution_status', 'MISSING'),
                expected_findings=len(expected['findings']), matched_findings=len(pairs),
                confirmed_findings=confirmed, unexpected_confirmed_findings=confirmed-len(pairs),
                finding_matches=[dict(expected_index=a, actual_index=b) for a, b in pairs],
                summary=check.get('summary', ''), stop_reason=check.get('investigation', {}).get('stop_reason'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--backend', choices=['codex', 'opencode'])
    parser.add_argument('--model')
    parser.add_argument('--case', action='append')
    parser.add_argument('--cases-dir', default=str(DEFAULT_CASES))
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--budget', type=float, default=600)
    args = parser.parse_args()
    if not 0 < args.timeout <= 600 or not 0 < args.budget <= 3600:
        parser.error('timeout must be (0,600], budget (0,3600]')
    if args.model and not args.backend:
        parser.error('--model requires --backend')
    cases = load_cases(args.cases_dir)
    if set(args.case or []) - set(cases):
        parser.error('Unknown case ID')
    output = ROOT / '.validator' / 'investigation-evals'
    output.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='run-', dir=output))
    summary = dict(directory=str(directory), backend=args.backend, model=args.model,
                   prepare_only=args.prepare_only, synthetic=True, cases=[])
    for name in dict.fromkeys(args.case or cases):
        print(('Preparing ' if args.prepare_only else 'Evaluating ') + name, file=sys.stderr, flush=True)
        store, config, expected = prepare(directory, name, cases)
        item = dict(case=name, db=str(store.path), config=str(config))
        # Retain the exact fixture/rubric for reproducibility, outside the model's Git repo.
        (store.path.parent / 'case.yaml').write_text(yaml.safe_dump(cases[name]), encoding='utf-8')
        if not args.prepare_only:
            try:
                result = analyze(store, 'target', ROOT / 'workflows', backend=args.backend, model=args.model,
                                 timeout=args.timeout, budget=args.budget, project_config=config,
                                 fixture_execution=cases[name]['execution'])
                check = next((c for c in result['report']['checks'] if c['check_id'] == 'CODE_IMPACT_001'), {})
                item.update(score(expected, check))
                report = store.path.parent / 'report.json'
                report.write_text(json.dumps(result, indent=2), encoding='utf-8')
                item['report_path'] = str(report)
            except Exception as exc:
                item.update(score(expected, {}), error=str(exc))
        summary['cases'].append(item)
        (directory / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    rows = summary['cases'] if not args.prepare_only else []
    summary.update(evaluated_cases=len(rows), matched_cases=sum(r['matched'] for r in rows),
                   expected_findings=sum(r['expected_findings'] for r in rows),
                   matched_findings=sum(r['matched_findings'] for r in rows),
                   unexpected_confirmed_findings=sum(r['unexpected_confirmed_findings'] for r in rows))
    (directory / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if args.prepare_only or all(r['matched'] for r in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
