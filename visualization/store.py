"""Atomic run snapshots + ordered events. Private config is never returned by queries."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / 'reports' / 'status_service'


def now(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class Store:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'status.sqlite3'
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, created TEXT NOT NULL, config TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cases (
                    run TEXT NOT NULL, id TEXT NOT NULL, state TEXT NOT NULL,
                    PRIMARY KEY(run,id));
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT NOT NULL, case_id TEXT NOT NULL,
                    at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS event_run ON events(run,seq);
            ''')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.db), timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn: yield conn
        finally: conn.close()

    def create(self, source, config, cases):
        run = uuid.uuid4().hex[:12]
        with self.connect() as conn:
            conn.execute('INSERT INTO runs VALUES(?,?,?,?)', (run, source, now(), json.dumps(config)))
            for case_id, state in cases.items():
                conn.execute('INSERT INTO cases VALUES(?,?,?)', (run, case_id, json.dumps(state)))
                self._event(conn, run, case_id, 'created', {'source': source})
        return run

    def _event(self, conn, run, case, kind, payload):
        conn.execute('INSERT INTO events(run,case_id,at,kind,payload) VALUES(?,?,?,?,?)',
                     (run, case, now(), kind, json.dumps(payload, ensure_ascii=False)))

    def save(self, run, case, state, kind, payload=None):
        with self.connect() as conn:
            conn.execute('UPDATE cases SET state=? WHERE run=? AND id=?', (json.dumps(state, ensure_ascii=False), run, case))
            self._event(conn, run, case, kind, payload or {})

    def config(self, run):
        with self.connect() as conn:
            row = conn.execute('SELECT config FROM runs WHERE id=?', (run,)).fetchone()
        if not row: raise KeyError('unknown run')
        return json.loads(row['config'])

    def state(self, run, case):
        with self.connect() as conn:
            row = conn.execute('SELECT state FROM cases WHERE run=? AND id=?', (run,case)).fetchone()
        if not row: raise KeyError('unknown run/case')
        return json.loads(row['state'])

    @staticmethod
    def public(state):
        return {k: v for k, v in state.items() if not k.startswith('_')}

    def view(self, run):
        with self.connect() as conn:
            row = conn.execute('SELECT id,source,created FROM runs WHERE id=?', (run,)).fetchone()
            if not row: raise KeyError('unknown run')
            cases = conn.execute('SELECT id,state FROM cases WHERE run=? ORDER BY id', (run,)).fetchall()
            cursor = conn.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE run=?', (run,)).fetchone()[0]
            return dict(row, cases=[{'id': r['id'], **self.public(json.loads(r['state']))} for r in cases], cursor=cursor)

    def runs(self):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute('SELECT id,source,created FROM runs ORDER BY created DESC,id')]

    def events(self, run, after=0, limit=100):
        self.config(run)
        if after < 0 or not 1 <= limit <= 100: raise ValueError('invalid event cursor/limit')
        with self.connect() as conn:
            rows = conn.execute('SELECT * FROM events WHERE run=? AND seq>? ORDER BY seq LIMIT ?', (run,after,limit)).fetchall()
        return [{**dict(r), 'payload': json.loads(r['payload'])} for r in rows]

    def recover(self):
        """Only the exclusive service owner calls this, never a read-only client."""
        for run in self.runs():
            for case in self.view(run['id'])['cases']:
                state = self.state(run['id'], case['id'])
                if state['status'] == 'RUNNING':
                    state.update(status='INTERRUPTED', error='Service exited during execution; explicit retry restarts this stage.')
                    state['revision'] += 1
                    self.save(run['id'], case['id'], state, 'interrupted')
