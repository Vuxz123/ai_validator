"""Finding-driven target source retrieval for the independent verification pass."""
from pathlib import PurePosixPath
from itertools import zip_longest
import re
import time

from .git import git


def declared_types(source):
    # Lexical retrieval hints only: mask comments and literal text before matching
    # declarations. This is deliberately not C# symbol or preprocessor resolution.
    masked = re.sub(r'//[^\r\n]*|/\*.*?\*/|(?P<raw>"{3,}).*?(?P=raw)|'
                    r'@"(?:""|[^"])*"|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                    ' ', source, flags=re.DOTALL)
    return re.findall(r'\b(?:class|struct|interface|record(?:\s+(?:class|struct))?)\s+'
                      r'([A-Za-z_][A-Za-z0-9_]*)', masked)


def collect(build, finding, deadline, max_bytes=300000, max_files=20):
    result = {'sha': build['target_sha'], 'files': {}, 'caller_files': [],
              'complete': True, 'limitations': [], 'search_names': []}
    deadline = min(deadline, time.monotonic() + 45)
    seeds = list(dict.fromkeys(item['file'] for item in finding['evidence']))
    remaining = max_bytes

    def omit(message):
        result['complete'] = False
        result['limitations'].append(message)

    def read(path):
        nonlocal remaining
        if not path:
            omit('Empty source path rejected.')
            return ''
        if path in result['files']:
            return result['files'][path]
        if len(result['files']) >= max_files:
            omit('Verification file limit reached: ' + path)
            return ''
        try:
            raw = git(build['repo'], 'show', f"{build['target_sha']}:{path}",
                      max_bytes=max(remaining, 1), deadline=deadline)
            if len(raw) > remaining:
                raise ValueError('Verification byte budget exhausted')
            text = raw.decode('utf-8-sig')
            if '\0' in text:
                raise ValueError('Binary source')
            result['files'][path] = text
            remaining -= len(raw)
            return text
        except (ValueError, OSError, UnicodeError) as exc:
            omit('Verification source unavailable/over budget: ' + path + ': ' + str(exc)[:200])
            return ''

    try:
        if len(seeds) > 4:
            omit('Only first four evidence files searched for callers.')
        searches = []
        name_limit = max(1, 8 // max(1, len(seeds[:4])))
        for path in seeds[:4]:
            source = read(path)
            if path.endswith('.cs'):
                stem = PurePosixPath(path).stem
                names = list(dict.fromkeys(([stem] if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', stem)
                                           else []) + declared_types(source)))
                if len(names) > name_limit:
                    omit('Verification type-name quota reached for: ' + path)
                searches.append((path, names[:name_limit]))
        result['search_names'] = list(dict.fromkeys(n for _, names in searches for n in names))
        if any(p.endswith('.cs') for p in seeds) and not result['search_names']:
            omit('No C# type name available for caller search.')
        groups = []
        result['caller_searches'] = []
        for seed, names in searches:
            if not names:
                continue
            try:
                raw = git(build['repo'], 'grep', '-l', '-z', '-I', '-E', '-e',
                          r'\b(' + '|'.join(names) + r')\b',
                          build['target_sha'], '--', '*.cs', max_bytes=32000, truncate=True, deadline=deadline)
            except ValueError as exc:
                if str(exc):
                    raise
                raw = b''  # git grep exit 1, no matches
            if len(raw) > 32000:
                omit('Verification caller search output truncated.')
            prefix = build['target_sha'] + ':'
            # Only NUL-terminated records are complete. Never interpret a cut-off
            # SHA: prefix as an empty path (git show SHA: would read the root tree).
            records = raw[:32000].split(b'\0')[:-1]
            paths = sorted({p[len(prefix):] for record in records
                            for p in [record.decode('utf-8')]
                            if p.startswith(prefix) and p[len(prefix):]
                            and p[len(prefix):] not in seeds})
            result['caller_searches'].append({'seed_file': seed, 'names': names,
                                              'candidate_count': len(paths)})
            groups.append(paths[:max_files])
            if len(paths) > max_files:
                omit('Verification caller count exceeds file limit.')
        # Interleave per-seed candidates so a noisy type cannot occupy every slot.
        paths = list(dict.fromkeys(p for row in zip_longest(*groups) for p in row if p))
        result['caller_files'] = paths[:max_files]
        if len(paths) > max_files:
            omit('Verification combined caller count exceeds file limit.')
        for path in paths[:max_files]:
            read(path)
        result['limitations'].append('Type-name text matches are caller candidates, not resolved call paths; inspect guards and call sites.')
    except Exception as exc:
        omit('Verification retrieval failed: ' + str(exc)[:300])
    return result
