"""One real review and verification on synthetic code; may consume provider usage."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validator.agent import invoke, validate_review, validate_verification
from validator.backends import Backend, resolve_executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', required=True, choices=['codex', 'opencode'])
    parser.add_argument('--model')
    parser.add_argument('--timeout', type=float, default=60)
    args = parser.parse_args()
    backend = Backend(args.backend, args.model, resolve_executable(args.backend))
    build = {'build_id': 'synthetic-smoke', 'target_sha': 'a' * 40, 'baseline_sha': 'b' * 40}
    context = {'files': {'Reward.cs': 'class Reward { void StartAd() { Grant(); } void Grant() {} }'},
               'diff': '+ void StartAd() { Grant(); }', 'limitations': ['Synthetic smoke test only.']}
    check = {'id': 'SMOKE_001', 'description': 'Does StartAd call Grant directly? '
             'PASS if yes, FAIL if no. Cite line 1. This is synthetic code.',
             'evidence_required': ['Direct call location']}
    request = {'phase': 'review', 'build': build, 'context': context, 'check': check}
    review = validate_review(invoke(backend, request, args.timeout), check, build, context)
    # Exercise the verify protocol independently, without inventing a production finding.
    finding = {'summary': 'StartAd directly calls Grant.', 'evidence': review['evidence']}
    verification = validate_verification(invoke(backend, {**request, 'phase': 'verify',
                                                          'finding': finding}, args.timeout), build, context)
    print(json.dumps({'backend': args.backend, 'model': args.model, 'review': review,
                      'verification': verification}, indent=2))


if __name__ == '__main__':
    main()
