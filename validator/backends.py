"""Built-in CLI transports. Each call has a fresh session and frozen input only."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time


@dataclass
class Backend:
    name: str
    model: str | None = None
    argv: list[str] | None = None
    executable: str | None = None


def resolve_executable(name, executable=None):
    found = executable or shutil.which(name)
    if not found:
        raise ValueError(f'{name} CLI not found on PATH; install/login or use --agent-executable')
    path = Path(found).resolve()
    if not path.is_file():
        raise ValueError(f'CLI executable does not exist: {path}')
    if path.suffix.lower() in ('.cmd', '.bat', '.ps1'):
        # Known npm layouts: never interpolate prompts into cmd.exe/PowerShell.
        if name == 'codex':
            entry = path.parent / 'node_modules/@openai/codex/bin/codex.js'
            node = shutil.which('node')
            if entry.is_file() and node:
                return [node, str(entry)]
        elif name == 'opencode':
            entry = path.parent / 'node_modules/opencode-ai/bin/opencode.exe'
            if entry.is_file():
                return [str(entry)]
        raise ValueError('Unsupported shell launcher; use --agent-executable with a native executable')
    return [str(path)]


def response_schema(request):
    evidence = {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False,
        'properties': {'sha': {'type': 'string'}, 'file': {'type': 'string'},
                       'line': {'type': 'integer'}, 'reason': {'type': 'string'}},
        'required': ['sha', 'file', 'line', 'reason'],
    }}
    properties = {'summary': {'type': 'string'}, 'evidence': evidence}
    if request['phase'] == 'investigate':
        finding = response_schema({**request, 'phase': 'review'})
        finding['properties']['status'] = {'type': 'string', 'enum': ['FAIL']}
        properties.update(action={'type':'string','enum':['retrieve','finish']},
                          status={'type':'string','enum':['PASS','FAIL','UNKNOWN','NOT_APPLICABLE']},
                          limitations={'type':'array','items':{'type':'string'}},
                          findings={'type':'array','items':finding,'maxItems':5},
                          requests={'type':'array','maxItems':3,'items':{
                              'type':'object','additionalProperties':False,
                              'properties':{'kind':{'type':'string','enum':['read','search','graph','find','read_lines']},
                                            'path':{'type':'string'},'query':{'type':'string'},
                                            'start_line':{'type':'integer'},'end_line':{'type':'integer'},
                                            'snapshot':{'type':'string','enum':['target','baseline']}},
                              'required':['kind','path','query','snapshot','start_line','end_line']}})
        return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    if request['phase'] == 'verify':
        properties['verdict'] = {'type': 'string', 'enum': ['CONFIRMED', 'REJECTED', 'INCONCLUSIVE']}
    else:
        properties.update(check_id={'type': 'string', 'enum': [request['check']['id']]},
                          status={'type': 'string', 'enum': ['PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE']},
                          limitations={'type': 'array', 'items': {'type': 'string'}})
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


def stop_tree(process):
    if os.name == 'nt':
        result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
        if result.returncode and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
            raise OSError('Could not stop CLI process tree: ' + result.stderr.decode(errors='replace')[:1000])
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def execute(argv, directory, stdin_bytes, env, timeout, result_file=None):
    with tempfile.TemporaryFile() as input_file, tempfile.TemporaryFile() as output, \
            tempfile.TemporaryFile() as errors:
        input_file.write(stdin_bytes)
        input_file.seek(0)
        options = ({'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                   if os.name == 'nt' else {'start_new_session': True})
        process = subprocess.Popen(argv, stdin=input_file, stdout=output, stderr=errors,
                                   cwd=directory, env=env, **options)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(argv, timeout)
                if max(os.fstat(f.fileno()).st_size for f in (output, errors)) > 8 * 1024 * 1024:
                    raise ValueError('CLI logs exceed 8 MiB')
                if result_file and result_file.exists() and result_file.stat().st_size > 262144:
                    raise ValueError('CLI response exceeds 256 KiB')
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            if process.returncode:
                raise ValueError(f'CLI exited with code {process.returncode}; check CLI authentication/model')
            output.seek(0)
            data = output.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise ValueError('CLI logs exceed 8 MiB')
            return data
        finally:
            if process.poll() is None:
                stop_tree(process)


def parse_opencode(data):
    fragments, finished = [], False
    for line in data.decode('utf-8').splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError('Invalid OpenCode event')
        if event.get('type') == 'error':
            raise ValueError('OpenCode returned an error event; check provider authentication/model')
        if event.get('type') == 'text':
            part = event.get('part', {})
            if not isinstance(part, dict) or not isinstance(part.get('text'), str):
                raise ValueError('Invalid OpenCode text event')
            fragments.append(part['text'])
        if event.get('type') == 'step_finish':
            part = event.get('part')
            if not isinstance(part, dict):
                raise ValueError('Invalid OpenCode completion event')
            finished = part.get('reason') == 'stop'
    if not finished or not fragments:
        raise ValueError('OpenCode stream did not finish with a final text response')
    text = ''.join(fragments).strip()
    if text.startswith('```json\n') and text.endswith('\n```'):
        text = text[8:-4]
    if len(text.encode('utf-8')) > 262144:
        raise ValueError('CLI response exceeds 256 KiB')
    return json.loads(text)


def invoke_backend(backend, request, timeout):
    if backend.name not in ('codex', 'opencode'):
        raise ValueError('Unknown backend')
    argv = backend.argv or resolve_executable(backend.name, backend.executable)
    with tempfile.TemporaryDirectory(prefix=f'validator-{backend.name}-') as directory:
        root = Path(directory)
        schema = response_schema(request)
        payload = {**request, 'output_schema': schema}
        data = json.dumps(payload, ensure_ascii=True).encode('utf-8')
        env = dict(os.environ)
        if backend.name == 'codex':
            schema_file, result_file = root / 'schema.json', root / 'result.json'
            schema_file.write_text(json.dumps(schema), encoding='utf-8')
            command = argv + ['exec', '--ignore-user-config', '--sandbox', 'read-only',
                              '--skip-git-repo-check', '--ephemeral', '--color', 'never',
                              '--output-schema', str(schema_file),
                              '--output-last-message', str(result_file)]
            if backend.model:
                command += ['--model', backend.model]
            execute(command + ['-'], root, data, env, timeout, result_file)
            if not result_file.exists():
                raise ValueError('Codex did not write its final response')
            with result_file.open('rb') as file:
                answer = file.read(262145)
            if len(answer) > 262144:
                raise ValueError('CLI response exceeds 256 KiB')
            response = json.loads(answer)
        else:
            input_file = root / 'request.json'
            input_file.write_bytes(data)
            env['OPENCODE_CONFIG_CONTENT'] = json.dumps({
                'share': 'disabled', 'permission': {'*': 'deny'},
                'agent': {'validator_check': {'description': 'Frozen build checklist reviewer',
                    'mode': 'primary', 'permission': {'*': 'deny'},
                    'prompt': 'Review only the attached validator request. Never call tools. '
                              'Follow its instructions and output_schema. Return one JSON object.'}},
            })
            env['OPENCODE_PERMISSION'] = json.dumps({'*': 'deny'})
            env['OPENCODE_AUTO_SHARE'] = 'false'
            env['OPENCODE_DISABLE_AUTOUPDATE'] = 'true'
            command = argv + ['run', '--pure', '--format', 'json', '--agent', 'validator_check']
            if backend.model:
                command += ['--model', backend.model]
            command += ['--file', str(input_file), '--', 'Analyze the attached validator request. Return JSON only.']
            response = parse_opencode(execute(command, root, b'', env, timeout))
    if not isinstance(response, dict):
        raise ValueError('Backend response must be a JSON object')
    return response
