import { Database } from 'node:sqlite';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(ROOT, '.data');
await mkdir(DATA_DIR, { recursive: true });

const db = new Database(path.join(DATA_DIR, 'schedule.sqlite'));
db.exec(`
  PRAGMA journal_mode = WAL;
  PRAGMA foreign_keys = ON;
  CREATE TABLE IF NOT EXISTS schedule_items (
    id TEXT PRIMARY KEY, date TEXT NOT NULL, time TEXT NOT NULL, type TEXT NOT NULL,
    title TEXT NOT NULL, shipment_id TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL DEFAULT '', dependencies TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'scheduled', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
  ) STRICT;
  CREATE INDEX IF NOT EXISTS schedule_items_date_time ON schedule_items(date, time);
  CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
`);
if (!db.prepare('PRAGMA table_info(schedule_items)').all().some(column => column.name === 'dependencies')) {
  db.exec("ALTER TABLE schedule_items ADD COLUMN dependencies TEXT NOT NULL DEFAULT '[]'");
}

const mapItem = row => row && ({
  id: row.id, date: row.date, time: row.time, type: row.type, title: row.title,
  shipmentId: row.shipment_id, party: row.owner, dependencies: JSON.parse(row.dependencies), status: row.status,
  createdAt: row.created_at, updatedAt: row.updated_at
});
const selectById = db.prepare('SELECT * FROM schedule_items WHERE id = ?');

// Copy the existing demo schedule into SQLite once so the calendar works on first run.
if (!db.prepare('SELECT value FROM app_meta WHERE key = ?').get('demo_schedule_v1')) {
  const seed = JSON.parse(await readFile(path.join(ROOT, 'mock/day-schedules.json'), 'utf8'));
  const insert = db.prepare(`INSERT OR IGNORE INTO schedule_items
    (id, date, time, type, title, shipment_id, owner, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
  const now = new Date().toISOString();
  db.exec('BEGIN IMMEDIATE');
  try {
    for (const [date, day] of Object.entries(seed)) {
      for (const [index, item] of (day.items || []).entries()) {
        insert.run(`demo-${date}-${index + 1}`, date, item.time, item.type, item.title,
          item.shipmentId || '', item.party || '', item.status || 'scheduled', now, now);
      }
    }
    db.prepare('INSERT INTO app_meta(key, value) VALUES(?, ?)').run('demo_schedule_v1', now);
    db.exec('COMMIT');
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  }
}

const insertItem = db.prepare(`INSERT INTO schedule_items
  (id, date, time, type, title, shipment_id, owner, dependencies, status, created_at, updated_at)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
const updateItem = db.prepare(`UPDATE schedule_items SET date = ?, time = ?, type = ?, title = ?,
  shipment_id = ?, owner = ?, dependencies = ?, status = ?, updated_at = ? WHERE id = ?`);
const validTypes = new Set(['packed', 'customs', 'in_transit', 'delivered', 'deadline', 'alert', 'review', 'other']);
const validStatuses = new Set(['open', 'pending', 'scheduled', 'in_progress', 'done', 'cancelled']);
const allowedFields = new Set(['date', 'time', 'type', 'title', 'shipmentId', 'party', 'dependencies', 'status']);

function badRequest(message) { throw Object.assign(new Error(message), { status: 400 }); }
function validateDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) badRequest('date must be a real date in YYYY-MM-DD format.');
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(+parsed) || parsed.toISOString().slice(0, 10) !== value) badRequest('date must be a real date in YYYY-MM-DD format.');
  return value;
}
function normalizeInput(input, current = {}) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) badRequest('A JSON object is required.');
  for (const key of Object.keys(input)) if (!allowedFields.has(key)) badRequest(`Unsupported schedule field: ${key}.`);
  const value = {
    date: input.date ?? current.date, time: input.time ?? current.time, type: input.type ?? current.type,
    title: input.title ?? current.title, shipmentId: input.shipmentId ?? current.shipmentId ?? '',
    party: input.party ?? current.party ?? '', dependencies: input.dependencies ?? current.dependencies ?? [],
    status: input.status ?? current.status ?? 'scheduled'
  };
  validateDate(value.date);
  if (typeof value.time !== 'string' || !/^([01]\d|2[0-3]):[0-5]\d$/.test(value.time)) badRequest('time must use 24-hour HH:MM format.');
  if (typeof value.type !== 'string' || !validTypes.has(value.type)) badRequest(`type must be one of: ${[...validTypes].join(', ')}.`);
  if (typeof value.title !== 'string' || !value.title.trim() || value.title.length > 240) badRequest('title is required and must be at most 240 characters.');
  if (typeof value.shipmentId !== 'string' || value.shipmentId.length > 120) badRequest('shipmentId must be a string of at most 120 characters.');
  if (typeof value.party !== 'string' || value.party.length > 160) badRequest('party must be a string of at most 160 characters.');
  if (!Array.isArray(value.dependencies) || value.dependencies.length > 50 || value.dependencies.some(id => typeof id !== 'string' || !id || id.length > 120) || new Set(value.dependencies).size !== value.dependencies.length) badRequest('dependencies must be a list of up to 50 unique schedule item IDs.');
  if (typeof value.status !== 'string' || !validStatuses.has(value.status)) badRequest(`status must be one of: ${[...validStatuses].join(', ')}.`);
  return { ...value, title: value.title.trim(), shipmentId: value.shipmentId.trim(), party: value.party.trim() };
}

export function listCalendarEvents(month) {
  if (typeof month !== 'string' || !/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) badRequest('month must use YYYY-MM format.');
  return db.prepare(`SELECT date, time, type, title FROM schedule_items
    WHERE substr(date, 1, 7) = ? ORDER BY date, time`).all(month).map(row => ({
    date: row.date, level: ['alert', 'deadline'].includes(row.type) ? 'major' : 'minor',
    label: `${row.time} · ${row.title}`
  }));
}

export function listScheduleDay(date) {
  validateDate(date);
  const items = db.prepare('SELECT * FROM schedule_items WHERE date = ? ORDER BY time').all(date).map(mapItem);
  return { date, items };
}

export function createScheduleItem(input) {
  const item = normalizeInput(input);
  const id = randomUUID(), now = new Date().toISOString();
  ensureDependenciesExist(item.dependencies, id);
  insertItem.run(id, item.date, item.time, item.type, item.title, item.shipmentId, item.party, JSON.stringify(item.dependencies), item.status, now, now);
  return mapItem(selectById.get(id));
}

export function updateScheduleItem(id, input) {
  const row = selectById.get(id);
  if (!row) throw Object.assign(new Error('Schedule item not found.'), { status: 404 });
  const item = normalizeInput(input, mapItem(row));
  ensureDependenciesExist(item.dependencies, id);
  updateItem.run(item.date, item.time, item.type, item.title, item.shipmentId, item.party, JSON.stringify(item.dependencies), item.status, new Date().toISOString(), id);
  return mapItem(selectById.get(id));
}

export function removeScheduleItem(id) {
  const dependent = db.prepare('SELECT id, dependencies FROM schedule_items WHERE id != ?').all(id)
    .find(row => JSON.parse(row.dependencies).includes(id));
  if (dependent) throw Object.assign(new Error(`Schedule item is required by ${dependent.id}; update its dependencies first.`), { status: 409 });
  const result = db.prepare('DELETE FROM schedule_items WHERE id = ?').run(id);
  if (!result.changes) throw Object.assign(new Error('Schedule item not found.'), { status: 404 });
}

function ensureDependenciesExist(dependencies, itemId) {
  const pending = [...dependencies], visited = new Set();
  while (pending.length) {
    const dependencyId = pending.pop();
    if (dependencyId === itemId) badRequest('Schedule dependencies cannot form a cycle.');
    if (visited.has(dependencyId)) continue;
    visited.add(dependencyId);
    const dependency = selectById.get(dependencyId);
    if (!dependency) badRequest(`Dependency ${dependencyId} does not exist.`);
    pending.push(...JSON.parse(dependency.dependencies));
  }
}
