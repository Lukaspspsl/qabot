import { Database } from "bun:sqlite";
import { join } from "path";

const DB_PATH = process.env.OBS_DB_PATH ?? join(import.meta.dir, "..", "obs.db");

export const db = new Database(DB_PATH);

db.run(`
  CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    source_app   TEXT DEFAULT 'qabot',
    hook_event_type TEXT NOT NULL,
    tool_name    TEXT,
    tool_use_id  TEXT,
    test_name    TEXT,
    test_step    TEXT,
    status       TEXT DEFAULT 'INFO',
    detail       TEXT,
    payload      TEXT
  )
`);
db.run(`CREATE INDEX IF NOT EXISTS idx_session ON events(session_id)`);
db.run(`CREATE INDEX IF NOT EXISTS idx_ts ON events(ts)`);
db.run(`CREATE INDEX IF NOT EXISTS idx_status ON events(status)`);

export interface Event {
  id?: number;
  ts: string;
  session_id: string;
  source_app?: string;
  hook_event_type: string;
  tool_name?: string;
  tool_use_id?: string;
  test_name?: string;
  test_step?: string;
  status?: string;
  detail?: string;
  payload?: string;
}

const insertStmt = db.prepare(`
  INSERT INTO events (ts, session_id, source_app, hook_event_type, tool_name, tool_use_id, test_name, test_step, status, detail, payload)
  VALUES ($ts, $session_id, $source_app, $hook_event_type, $tool_name, $tool_use_id, $test_name, $test_step, $status, $detail, $payload)
`);

export function insertEvent(e: Event): number {
  const result = insertStmt.run({
    $ts: e.ts,
    $session_id: e.session_id,
    $source_app: e.source_app ?? "qabot",
    $hook_event_type: e.hook_event_type,
    $tool_name: e.tool_name ?? null,
    $tool_use_id: e.tool_use_id ?? null,
    $test_name: e.test_name ?? null,
    $test_step: e.test_step ?? null,
    $status: e.status ?? "INFO",
    $detail: e.detail ?? null,
    $payload: typeof e.payload === "object" ? JSON.stringify(e.payload) : (e.payload ?? null),
  });
  return result.lastInsertRowid as number;
}

export interface EventQuery {
  session?: string;
  status?: string;
  tool?: string;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}

export function queryEvents(q: EventQuery): Event[] {
  const conditions: string[] = [];
  const params: Record<string, unknown> = {};

  if (q.session) { conditions.push("session_id = $session"); params.$session = q.session; }
  if (q.status)  { conditions.push("status = $status");      params.$status = q.status; }
  if (q.tool)    { conditions.push("tool_name = $tool");      params.$tool = q.tool; }
  if (q.from)    { conditions.push("ts >= $from");            params.$from = q.from; }
  if (q.to)      { conditions.push("ts <= $to");              params.$to = q.to; }

  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
  const lim = Math.min(q.limit ?? 500, 2000);
  const off = q.offset ?? 0;

  return db.query(`SELECT * FROM events ${where} ORDER BY ts DESC LIMIT ${lim} OFFSET ${off}`).all(params) as Event[];
}

export interface SessionSummary {
  session_id: string;
  event_count: number;
  pass_count: number;
  fail_count: number;
  warn_count: number;
  first_ts: string;
  last_ts: string;
}

export function querySessions(): SessionSummary[] {
  return db.query(`
    SELECT
      session_id,
      COUNT(*) as event_count,
      SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END) as pass_count,
      SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END) as fail_count,
      SUM(CASE WHEN status = 'WARN' OR status = 'BLOCKED' THEN 1 ELSE 0 END) as warn_count,
      MIN(ts) as first_ts,
      MAX(ts) as last_ts
    FROM events
    GROUP BY session_id
    ORDER BY last_ts DESC
    LIMIT 50
  `).all() as SessionSummary[];
}

export function countEvents(): number {
  const row = db.query("SELECT COUNT(*) as n FROM events").get({}) as { n: number };
  return row.n;
}

export function queryStatusDistribution(session_id?: string): Record<string, number> {
  const safeSession = session_id ? session_id.replace(/[^a-zA-Z0-9_-]/g, "") : null;
  const where = safeSession ? `WHERE session_id = '${safeSession}'` : "";
  const rows = db.query(`SELECT status, COUNT(*) as n FROM events ${where} GROUP BY status`).all({}) as { status: string; n: number }[];
  return Object.fromEntries(rows.map(r => [r.status, r.n]));
}
