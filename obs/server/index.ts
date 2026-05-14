import { join } from "path";
import { insertEvent, queryEvents, querySessions, countEvents, queryStatusDistribution } from "./db.ts";

const PORT = parseInt(process.env.OBS_PORT ?? "4000");
const CLIENT_HTML = Bun.file(join(import.meta.dir, "..", "client", "index.html"));

// SSE subscribers
const subscribers = new Set<ReadableStreamDefaultController>();

function broadcast(event: object) {
  const data = `data: ${JSON.stringify(event)}\n\n`;
  const dead: ReadableStreamDefaultController[] = [];
  for (const ctrl of subscribers) {
    try { ctrl.enqueue(new TextEncoder().encode(data)); }
    catch { dead.push(ctrl); }
  }
  dead.forEach(c => subscribers.delete(c));
}

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders() },
  });
}

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    const method = req.method;

    if (method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    // POST /events — ingest
    if (method === "POST" && url.pathname === "/events") {
      let body: Record<string, unknown>;
      try {
        body = await req.json();
      } catch {
        return json({ error: "invalid json" }, 400);
      }
      const id = insertEvent({
        ts: (body.timestamp as string) ?? new Date().toISOString(),
        session_id: (body.session_id as string) ?? "unknown",
        source_app: (body.source_app as string) ?? "qabot",
        hook_event_type: (body.hook_event_type as string) ?? "tool_use",
        tool_name: body.tool_name as string,
        tool_use_id: body.tool_use_id as string,
        test_name: body.test_name as string,
        test_step: body.test_step as string,
        status: body.status as string,
        detail: body.detail as string,
        payload: JSON.stringify(body.payload ?? body),
      });
      const event = { id, ...body };
      broadcast(event);
      return json({ ok: true, id });
    }

    // GET /events — query
    if (method === "GET" && url.pathname === "/events") {
      const p = url.searchParams;
      const events = queryEvents({
        session: p.get("session") ?? undefined,
        status: p.get("status") ?? undefined,
        tool: p.get("tool") ?? undefined,
        from: p.get("from") ?? undefined,
        to: p.get("to") ?? undefined,
        limit: p.get("limit") ? parseInt(p.get("limit")!) : undefined,
        offset: p.get("offset") ? parseInt(p.get("offset")!) : undefined,
      });
      return json(events);
    }

    // GET /sessions
    if (method === "GET" && url.pathname === "/sessions") {
      return json(querySessions());
    }

    // GET /health
    if (method === "GET" && url.pathname === "/health") {
      return json({ ok: true, event_count: countEvents() });
    }

    // GET /stats
    if (method === "GET" && url.pathname === "/stats") {
      const session = url.searchParams.get("session") ?? undefined;
      return json(queryStatusDistribution(session));
    }

    // GET /stream — SSE
    if (method === "GET" && url.pathname === "/stream") {
      let ctrl: ReadableStreamDefaultController;
      const stream = new ReadableStream({
        start(c) {
          ctrl = c;
          subscribers.add(ctrl);
          // heartbeat every 25s
          const hb = setInterval(() => {
            try { ctrl.enqueue(new TextEncoder().encode(": heartbeat\n\n")); }
            catch { clearInterval(hb); }
          }, 25000);
        },
        cancel() {
          subscribers.delete(ctrl);
        },
      });
      return new Response(stream, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          "Connection": "keep-alive",
          ...corsHeaders(),
        },
      });
    }

    // GET / — dashboard
    if (method === "GET" && (url.pathname === "/" || url.pathname === "/index.html")) {
      return new Response(CLIENT_HTML);
    }

    return json({ error: "not found" }, 404);
  },
});

console.log(`Obs server running at http://localhost:${PORT}`);
