"""SQLite repository. Plan payloads are immutable; decisions are separate records."""
import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix):
    return prefix + '_' + uuid4().hex[:16]


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


class Repository:
    def __init__(self, path):
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.migrate()

    def migrate(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS scenarios(id TEXT PRIMARY KEY, trial_id TEXT NOT NULL, parent_id TEXT,
            payload TEXT NOT NULL, input_dataset TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL REFERENCES scenarios(id),
            status TEXT NOT NULL CHECK(status IN ('approved','rejected')), approver TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY, action TEXT NOT NULL, entity_id TEXT, actor TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS previews(id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, dataset_id TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, source_id TEXT NOT NULL, content_hash TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_registry(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS acknowledgements(alert_id TEXT PRIMARY KEY, actor TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS immutable_scenarios_update BEFORE UPDATE ON scenarios BEGIN SELECT RAISE(ABORT,'Scenarios are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_scenarios_delete BEFORE DELETE ON scenarios BEGIN SELECT RAISE(ABORT,'Scenarios are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_audit_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'Audit is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_audit_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'Audit is append-only'); END;
        ''')
        self.db.execute('INSERT OR IGNORE INTO migrations VALUES(1,?)', (now(),))
        self.db.commit()

    @contextmanager
    def transaction(self):
        with self.lock:
            try:
                yield
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def setting(self, key, default=None):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, encode(value)))

    def dataset(self):
        key = self.setting('dataset_id')
        row = self.db.execute('SELECT payload FROM datasets WHERE id=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_dataset(self, dataset):
        key = identifier('dataset')
        self.db.execute('INSERT INTO datasets VALUES(?,?,?)', (key, encode(dataset), now()))
        self.set_setting('dataset_id', key)
        return key

    def audit(self, action, entity_id=None, actor='local planner', payload=None):
        self.db.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)', (identifier('audit'),action,entity_id,actor,encode(payload or {}),now()))

    def save_plan(self, plan, dataset):
        content = encode(plan)
        self.db.execute('INSERT INTO scenarios VALUES(?,?,?,?,?,?,?)', (plan['id'],plan['trial_id'],plan.get('parent_scenario_id'),content,encode(dataset),hashlib.sha256(content.encode()).hexdigest(),now()))
        self.audit('scenario.generated', plan['id'], payload={'calculation_version':plan.get('calculation_version'),'input_dataset_id':self.setting('dataset_id')})

    def plan(self, key):
        row = self.db.execute('SELECT * FROM scenarios WHERE id=?', (key,)).fetchone()
        if not row:
            raise KeyError('Scenario not found')
        plan = json.loads(row['payload'])
        decision = self.db.execute('SELECT * FROM decisions WHERE scenario_id=? ORDER BY rowid DESC LIMIT 1', (key,)).fetchone()
        plan['status'] = decision['status'] if decision else 'proposed'
        plan['approval'] = dict(decision) if decision else None
        plan['content_hash'] = row['content_hash']
        return plan

    def plan_dataset(self, key):
        row = self.db.execute('SELECT input_dataset FROM scenarios WHERE id=?', (key,)).fetchone()
        if not row:
            raise KeyError('Scenario not found')
        return json.loads(row[0])

    def plans(self, trial_id):
        return [self.plan(r[0]) for r in self.db.execute('SELECT id FROM scenarios WHERE trial_id=? ORDER BY rowid DESC', (trial_id,))]

    def decide(self, key, status, actor, note):
        plan = self.plan(key)
        if plan['status'] != 'proposed':
            raise ValueError('Only a proposed scenario can receive a decision')
        self.db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?)', (identifier('decision'),key,status,actor,note,now()))
        if status == 'approved':
            self.set_setting('approved_scenario_id', key)
        self.audit('scenario.' + status, key, actor, {'note':note})
        return self.plan(key)

    def events(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM events ORDER BY rowid')]

    def event(self, key):
        row = self.db.execute('SELECT payload FROM events WHERE id=?', (key,)).fetchone()
        if not row:
            raise KeyError('Change event not found')
        return json.loads(row[0])

    def save_event(self, event):
        self.db.execute('INSERT INTO events VALUES(?,?,?)', (event['id'], encode(event),now()))
        self.audit('change_event.ingested',event['id'],payload=event)

    def save_source(self, source):
        stamp = now()
        self.db.execute('INSERT INTO source_registry VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at',
                        (source['id'],encode(source),stamp,stamp))

    def sources(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM source_registry ORDER BY rowid')]

    def close(self):
        self.db.close()
