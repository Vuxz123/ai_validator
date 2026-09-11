"""Bounded windows with original Git source line numbers."""
from .git import git
from .workflows import require


def windows(repo, sha, path, kind, query, start, end, deadline):
    raw = git(repo, 'show', sha + ':' + path, max_bytes=16*1024*1024, deadline=deadline)
    text = raw.decode('utf-8-sig')
    require('\0' not in text, 'Binary source rejected')
    lines = text.splitlines()
    truncated = False
    if kind == 'read_lines':
        require(type(start) is int and type(end) is int and 1 <= start <= end
                and end-start < 400, 'read_lines requires a range of 1..400 lines')
        require(start <= len(lines), 'Start line exceeds file length')
        ranges = [(start, min(end, len(lines)))]
    else:
        require(isinstance(query, str) and 0 < len(query) <= 160 and '\n' not in query,
                'find requires a literal query of 1..160 characters')
        matches = [i+1 for i, line in enumerate(lines) if query in line]
        truncated = len(matches) > 10
        ranges = []
        for number in matches[:10]:
            a, b = max(1, number-12), min(len(lines), number+12)
            if ranges and a <= ranges[-1][1]+1:
                ranges[-1] = (ranges[-1][0], b)
            else:
                ranges.append((a, b))
    excerpts = []
    remaining = 24000
    for a, b in ranges:
        selected = []
        for line in lines[a-1:b]:
            size = len((line+'\n').encode('utf-8'))
            if size > remaining:
                truncated = True
                break
            selected.append(line)
            remaining -= size
        if selected:
            excerpts.append(dict(start_line=a, end_line=a+len(selected)-1, source='\n'.join(selected)+'\n'))
        if len(selected) < b-a+1:
            break
    return dict(path=path, total_lines=len(lines), excerpts=excerpts, truncated=truncated,
                partial=True)
