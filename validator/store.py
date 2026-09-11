"""Transactional build identity and monotonic branch/profile baselines."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS builds (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    build_id TEXT NOT NULL UNIQUE,
                    repo TEXT NOT NULL, branch TEXT NOT NULL, profile TEXT NOT NULL,
                    target_sha TEXT NOT NULL, baseline_sha TEXT,
                    confirmed_at TEXT,
                    analysis_status TEXT NOT NULL DEFAULT 'QUEUED',
                    report TEXT, error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS baselines (
                    repo TEXT, branch TEXT, profile TEXT,
                    sequence INTEGER NOT NULL, sha TEXT NOT NULL,
                    PRIMARY KEY(repo, branch, profile)
                );
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, build_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM builds WHERE build_id=?', (build_id,)).fetchone()
        if row is None:
            raise ValueError(f'Unknown build: {build_id}')
        result = dict(row)
        if result['report']:
            result['report'] = json.loads(result['report'])
        return result

    def order(self, build_id, repo, branch, profile, target_sha):
        repo = os.path.normcase(repo)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM builds WHERE build_id=?', (build_id,)).fetchone()
            if old:
                if tuple(old[k] for k in ('repo', 'branch', 'profile', 'target_sha')) != (
                    repo, branch, profile, target_sha
                ):
                    raise ValueError('Build ID already belongs to a different order')
            else:
                baseline = db.execute(
                    'SELECT sha FROM baselines WHERE repo=? AND branch=? AND profile=?',
                    (repo, branch, profile),
                ).fetchone()
                db.execute('''INSERT INTO builds
                    (build_id, repo, branch, profile, target_sha, baseline_sha)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (build_id, repo, branch, profile, target_sha,
                     baseline['sha'] if baseline else None))
        return self.get(build_id)

    def confirm(self, build_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM builds WHERE build_id=?', (build_id,)).fetchone()
            if not row:
                raise ValueError(f'Unknown build: {build_id}')
            db.execute('UPDATE builds SET confirmed_at=COALESCE(confirmed_at, CURRENT_TIMESTAMP) '
                       'WHERE build_id=?', (build_id,))
            db.execute('''INSERT INTO baselines VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(repo, branch, profile) DO UPDATE
                SET sequence=excluded.sequence, sha=excluded.sha
                WHERE excluded.sequence > baselines.sequence''',
                (row['repo'], row['branch'], row['profile'], row['sequence'], row['target_sha']))
        return self.get(build_id)

    def claim(self, build_id, retry=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT analysis_status FROM builds WHERE build_id=?',
                             (build_id,)).fetchone()
            if row is None:
                raise ValueError(f'Unknown build: {build_id}')
            if row['analysis_status'] == 'RUNNING':
                raise ValueError('Analysis is RUNNING; stop its worker before using recover')
            if row['analysis_status'] != 'QUEUED' and not retry:
                raise ValueError('Analysis already attempted; use --retry to run again')
            db.execute("UPDATE builds SET analysis_status='RUNNING', report=NULL, error=NULL "
                       'WHERE build_id=?', (build_id,))

    def finish(self, build_id, report=None, error=None):
        with self.connect() as db:
            db.execute('UPDATE builds SET analysis_status=?, report=?, error=? WHERE build_id=?',
                       ('FAILED' if error else 'COMPLETED',
                        json.dumps(report) if report else None, error, build_id))

    def recover(self, build_id):
        self.get(build_id)
        with self.connect() as db:
            db.execute("UPDATE builds SET analysis_status='FAILED', error='Manually recovered' "
                       "WHERE build_id=? AND analysis_status='RUNNING'", (build_id,))
        return self.get(build_id)
