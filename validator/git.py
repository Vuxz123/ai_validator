"""Read committed Git objects without checking out or executing project code."""

from pathlib import Path
import subprocess
import tempfile
import threading
import time


def git(repo, *args, max_bytes=4 * 1024 * 1024, truncate=False, deadline=None):
    timeout = min(60, deadline - time.monotonic()) if deadline else 60
    if timeout <= 0:
        raise TimeoutError('Analysis budget exhausted before Git operation')
    command = ['git', '-C', str(repo), *args]
    # Read at most limit+1 bytes, then terminate the producer. A reader thread lets
    # Windows pipes honor the timeout even when the producer has no output yet.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        captured = []
        reader = threading.Thread(target=lambda: captured.append(process.stdout.read(max_bytes + 1)),
                                  daemon=True)
        reader.start()
        try:
            reader.join(timeout)
            if reader.is_alive():
                raise subprocess.TimeoutExpired(command, timeout)
            data = captured[0]
            if len(data) > max_bytes:
                if not truncate:
                    raise ValueError('Git output limit exceeded')
                return data
            process.wait(timeout=max(0.01, min(timeout, deadline - time.monotonic())
                                     if deadline else timeout))
            if process.returncode:
                errors.seek(0)
                raise ValueError(errors.read(8192).decode('utf-8', errors='replace').strip())
            return data
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            reader.join()
            process.stdout.close()


def resolve(repo, target):
    root = git(repo, 'rev-parse', '--show-toplevel').decode('utf-8').strip()
    sha = git(root, 'rev-parse', '--verify', '--end-of-options',
              target + '^{commit}').decode('ascii').strip()
    return str(Path(root).resolve()), sha


def context_for(build, max_chars=120000, max_files=30, deadline=None):
    repo, baseline, target = (build[k] for k in ('repo', 'baseline_sha', 'target_sha'))

    def read(*args, **kwargs):
        return git(repo, *args, deadline=deadline, **kwargs)

    changed = read('diff', '--no-ext-diff', '--no-textconv', '--name-only', '--no-renames',
                  '-z', baseline, target, '--').decode('utf-8').split('\0')
    changed = [path for path in changed if path]
    diff_bytes = read('diff', '--no-ext-diff', '--no-textconv', '--no-renames',
                      '--unified=3', baseline, target, '--', max_bytes=max_chars, truncate=True)
    diff = diff_bytes[:max_chars].decode('utf-8', errors='replace')
    limitations = ['Graph/caller retrieval is not implemented; selection uses paths only.',
                   'Context contains changed text files only; unchanged dependencies are not included.']
    if len(diff_bytes) > max_chars:
        limitations.append('Diff truncated to context budget.')
    diff = diff[:max_chars]
    files = {}
    remaining = max_chars
    for path in changed[:max_files]:
        # Read only selected textual artifacts, including removals as diff context.
        if Path(path).suffix.lower() not in {'.cs', '.json', '.yaml', '.yml', '.unity',
                                             '.prefab', '.asset', '.meta', '.txt', '.md'}:
            continue
        try:
            size = int(read('cat-file', '-s', f'{target}:{path}'))
            if size > remaining:
                limitations.append(f'File omitted due to context budget: {path}')
                continue
            content = read('show', f'{target}:{path}', max_bytes=max(remaining, 1)).decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            limitations.append(f'No target text available: {path}')
            continue
        if '\0' in content:
            continue
        files[path] = content
        remaining -= len(content.encode('utf-8'))
    if len(changed) > max_files:
        limitations.append(f'Only first {max_files} changed paths considered for full-file context.')
    return {'changed_files': changed, 'diff': diff, 'files': files,
            'limitations': limitations}
