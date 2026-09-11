"""Deterministic protocol fixture, NOT an AI reviewer."""
import json
import sys
import time

mode = sys.argv[1]
request = json.load(sys.stdin)
if mode == 'timeout':
    time.sleep(10)
if mode == 'invalid':
    print('not json')
    sys.exit(0)
file = next(iter(request['context']['files']))
evidence = [{'sha': request['build']['target_sha'], 'file': file,
             'line': 99999 if mode == 'bad_line' else 1,
             'reason': 'Fixture evidence for protocol testing only.'}]
if request['phase'] == 'verify':
    print(json.dumps({'verdict': 'REJECTED' if mode == 'reject' else 'CONFIRMED',
                      'summary': 'Fixture verification.', 'evidence': evidence}))
else:
    print(json.dumps({'check_id': request['check']['id'], 'status': 'FAIL',
                      'summary': 'Fixture finding, not real AI analysis.',
                      'evidence': evidence, 'limitations': []}))
