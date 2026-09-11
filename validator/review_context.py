"""Bounded source expansion for one inconclusive review retry."""
from pathlib import PurePosixPath
import re

from .verification_context import collect as collect_sources


def collect(build, review, context, deadline):
    # Model text only ranks known repository paths; it cannot specify arbitrary reads.
    known = set(context.get('changed_files', [])) | set(context['files'])
    scripts = sorted(p for p in known if p.endswith('.cs'))
    def mentioned(text):
        words = re.findall(r'[A-Za-z_][A-Za-z0-9_]*', text)
        order = {word: i for i, word in reversed(list(enumerate(words)))}
        return sorted((p for p in scripts if PurePosixPath(p).stem in order),
                      key=lambda p: (order[PurePosixPath(p).stem], p))
    named = mentioned(review['summary'])
    cited = [e['file'] for e in review['evidence']]
    limited = mentioned('\n'.join(review['limitations']))
    missing = [p for p in scripts if p not in context['files']]
    # Do not dilute a focused question with unrelated types that exhaust caller limits.
    seeds = list(dict.fromkeys(named + cited + limited)) or missing or scripts
    extra = collect_sources(build, {'evidence': [{'file': p} for p in seeds[:4]]}, deadline)
    extra['seed_files'] = seeds[:4]
    if len(seeds) > 4:
        extra['limitations'].append('Review expansion uses at most four seed files; other scripts remain outside this retry.')
    extra['new_files'] = [p for p, text in extra['files'].items()
                          if context['files'].get(p) != text]
    return extra
