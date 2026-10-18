// Warning + notification state with dedupe. Optional JSON persistence (.data/ is git-ignored).
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
export class IntelStore {
  constructor(file = null) {
    this.file = file; this.warnings = new Map(); this.notifications = [];
    if (file) try { const d = JSON.parse(readFileSync(file, 'utf8')); (d.warnings || []).forEach(w => this.warnings.set(w.key, w)); this.notifications = d.notifications || []; } catch {}
  }
  save() { if (!this.file) return; try { mkdirSync(path.dirname(this.file), { recursive: true }); writeFileSync(this.file, JSON.stringify({ warnings: [...this.warnings.values()], notifications: this.notifications.slice(-500) })); } catch (e) { console.warn('intel store save failed', e.message); } }
  /** Insert or update; returns { warning, change: 'new'|'risk_changed'|'updated'|'reopened' }. */
  upsert(key, data, now) {
    const prev = this.warnings.get(key);
    if (!prev) { const w = { key, ...data, status: 'open', createdAt: now, updatedAt: now, history: [{ at: now, risk: data.risk, note: 'detected' }] }; this.warnings.set(key, w); return { warning: w, change: 'new' }; }
    const change = prev.status === 'resolved' ? 'reopened' : prev.risk !== data.risk ? 'risk_changed' : 'updated';
    const w = Object.assign(prev, data, { status: 'open', updatedAt: now, resolvedAt: null });
    if (change !== 'updated') w.history.push({ at: now, risk: data.risk, note: change });
    return { warning: w, change };
  }
  /** Resolve open warnings for a shipment whose keys are not in activeKeys. */
  resolveMissing(shipmentId, activeKeys, now) {
    const out = [];
    for (const w of this.warnings.values()) if (w.shipmentId === shipmentId && w.status !== 'resolved' && !activeKeys.has(w.key)) { w.status = 'resolved'; w.resolvedAt = now; w.updatedAt = now; w.history.push({ at: now, risk: w.risk, note: 'no longer detected' }); out.push(w); }
    return out;
  }
  list() { return [...this.warnings.values()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)); }
  findNotification(dedupeKey) { return this.notifications.find(n => n.dedupeKey === dedupeKey); }
  addNotification(n) { this.notifications.push(n); return n; }
}
