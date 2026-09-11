"""Fake Codex/OpenCode executable for offline protocol tests; never calls a model."""
import json
import os
from pathlib import Path
import sys
import subprocess
import time

kind, mode, *args = sys.argv[1:]
if mode == 'child_timeout':
    marker = os.environ['VALIDATOR_TEST_MARKER']
    subprocess.Popen([sys.executable, '-c',
                      'import time; from pathlib import Path; time.sleep(2); '
                      f'Path({marker!r}).write_text("orphan")'],
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    Path(marker + '.started').write_text('started')
    time.sleep(10)
if mode == 'timeout':
    time.sleep(10)
if kind == 'codex':
    request = json.load(sys.stdin)
    assert '--sandbox' in args and args[args.index('--sandbox') + 1] == 'read-only'
    assert '--ignore-user-config' in args
    schema = json.loads(Path(args[args.index('--output-schema') + 1]).read_text())
    assert schema['additionalProperties'] is False
else:
    assert '--pure' in args
    config = json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])
    assert config['share'] == 'disabled'
    assert config['agent']['validator_check']['permission'] == {'*': 'deny'}
    request = json.loads(Path(args[args.index('--file') + 1]).read_text())
if '--model' in args:
    assert args[args.index('--model') + 1] == 'test/model'
if mode == 'exit':
    sys.exit(17)
response = ({'verdict': 'CONFIRMED', 'summary': 'Fake verification', 'evidence': []}
            if request['phase'] == 'verify' else
            {'check_id': request['check']['id'], 'status': 'UNKNOWN',
             'summary': 'Fake CLI result', 'evidence': [], 'limitations': ['Fixture only']})
if kind == 'codex':
    Path(args[args.index('--output-last-message') + 1]).write_text(
        'invalid' if mode == 'invalid' else json.dumps(response))
    print('Progress log, not the final JSON')
else:
    print(json.dumps({'type': 'step_start'}))
    print(json.dumps({'type': 'text', 'part': {'text': json.dumps(response)}}))
    if mode == 'error_event':
        print(json.dumps({'type': 'error', 'error': {'name': 'ProviderError'}}))
    elif mode != 'incomplete':
        print(json.dumps({'type': 'step_finish', 'part': {'reason': 'stop'}}))
