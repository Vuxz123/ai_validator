"""JSON CLI for integration with a local build script."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from .git import resolve
from .store import Store


DEFAULT_WORKFLOWS = Path(__file__).resolve().parents[1] / 'workflows'


def analysis_options(parser):
    parser.add_argument('--project-config', help='Local YAML with Unity root, source groups and enabled rule packs')
    parser.add_argument('--workflows', default=str(DEFAULT_WORKFLOWS))
    agents = parser.add_mutually_exclusive_group()
    agents.add_argument('--agent-command', help='Path to a JSON argv array for a trusted agent adapter')
    agents.add_argument('--backend', choices=['codex', 'opencode'])
    parser.add_argument('--model', help='Optional model ID (OpenCode: provider/model)')
    parser.add_argument('--agent-executable', help='Optional native CLI executable or supported npm shim')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--budget', type=float, default=300)
    parser.add_argument('--unity-project', help='Unity directory inside the ordered Git repository; enables MCP context')
    parser.add_argument('--graph-timeout', type=float, default=120)
    parser.add_argument('--graph-root', action='append', help='Unity-relative Assets/Packages directory; defaults to both roots')


def start_worker(store, build_id, args):
    command = [sys.executable, '-m', 'validator', '--db', str(store.path),
               'analyze', build_id, '--workflows', str(Path(args.workflows).resolve()),
               '--timeout', str(args.timeout), '--budget', str(args.budget)]
    if args.agent_command:
        command += ['--agent-command', str(Path(args.agent_command).resolve())]
    if getattr(args, 'project_config', None):
        command += ['--project-config', str(Path(args.project_config).resolve())]
    if args.backend:
        command += ['--backend', args.backend]
    if args.model:
        command += ['--model', args.model]
    if args.agent_executable:
        command += ['--agent-executable', str(Path(args.agent_executable).resolve())]
    if getattr(args, 'unity_project', None):
        command += ['--unity-project', str(Path(args.unity_project).resolve()),
                    '--graph-timeout', str(args.graph_timeout)]
        for root in args.graph_root or []:
            command += ['--graph-root', root]
    options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS} \
        if os.name == 'nt' else {'start_new_session': True}
    log_path = store.path.parent / 'worker.log'
    with log_path.open('ab') as log:
        process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   close_fds=True, **options)
    return process.pid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='.validator/state.db')
    commands = parser.add_subparsers(dest='command', required=True)
    preview = commands.add_parser('preview', help='Explain routing for two commits without ordering, indexing or model calls')
    preview.add_argument('--repo', required=True)
    preview.add_argument('--baseline', required=True)
    preview.add_argument('--target', default='HEAD')
    preview.add_argument('--project-config')
    preview.add_argument('--workflows', default=str(DEFAULT_WORKFLOWS))
    index = commands.add_parser('index-unity', help='Prewarm a complete committed Unity index without ordering or confirming a build')
    index.add_argument('--repo', required=True)
    index.add_argument('--unity-project', help='Defaults to --repo; must be inside its Git root')
    index.add_argument('--target', default='HEAD')
    index.add_argument('--graph-root', action='append')
    index.add_argument('--index-timeout', type=float, default=1800)
    order = commands.add_parser('order')
    order.add_argument('--repo', required=True)
    order.add_argument('--branch', required=True)
    order.add_argument('--profile', default='default')
    order.add_argument('--target', required=True)
    order.add_argument('--build-id', default=None)
    order.add_argument('--no-start', action='store_true')
    analysis_options(order)
    analysis = commands.add_parser('analyze')
    analysis.add_argument('build_id')
    analysis.add_argument('--retry', action='store_true')
    analysis_options(analysis)
    for name in ('confirm', 'report', 'recover'):
        commands.add_parser(name).add_argument('build_id')
    args = parser.parse_args()
    if args.command in ('order', 'analyze') and (args.model or args.agent_executable) and not args.backend:
        parser.error('--model/--agent-executable requires --backend')
    try:
        if args.command == 'preview':
            from .git import git
            from .project import load_config, route
            from .workflows import load_workflows
            repo, target = resolve(args.repo, args.target)
            _, baseline = resolve(repo, args.baseline)
            paths = git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--name-only',
                        '--no-renames', '-z', baseline, target, '--').decode('utf-8').split('\0')
            config = load_config(args.project_config)
            result = dict(baseline_sha=baseline, target_sha=target,
                          routing_mode='project' if config is not None else 'legacy',
                          routing=route(load_workflows(args.workflows), [p for p in paths if p], config))
            print(json.dumps(result, ensure_ascii=True))
            return 0
        if args.command == 'index-unity':
            from .unity_mcp import prepare_index
            repo, sha = resolve(args.repo, args.target)
            result = prepare_index(repo, args.unity_project or args.repo, sha,
                                   Path(args.db).resolve().parent / 'unitygraph-cache',
                                   args.graph_root or ['Assets', 'Packages'], args.index_timeout)
            print(json.dumps(result, ensure_ascii=True))
            return 0 if result.get('status') == 'COMPLETED' else 1
        store = Store(args.db)
        if args.command == 'order':
            repo, sha = resolve(args.repo, args.target)
            result = store.order(args.build_id or str(uuid.uuid4()), repo, args.branch,
                                 args.profile, sha)
            result['worker_started'] = False
            if not args.no_start and result['analysis_status'] == 'QUEUED':
                try:
                    result['worker_pid'] = start_worker(store, result['build_id'], args)
                    result['worker_started'] = True
                except OSError as exc:
                    result['launch_error'] = str(exc)
        elif args.command == 'analyze':
            from .runner import analyze
            result = analyze(store, args.build_id, args.workflows, args.agent_command,
                             args.timeout, args.budget, args.retry,
                             args.backend, args.model, args.agent_executable,
                             args.unity_project, args.graph_timeout, args.graph_root, args.project_config)
        elif args.command == 'confirm':
            result = store.confirm(args.build_id)
        elif args.command == 'recover':
            result = store.recover(args.build_id)
        else:
            result = store.get(args.build_id)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
