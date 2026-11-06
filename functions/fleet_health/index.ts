import { Pool } from 'pg';
import { attachDatabasePool } from '@neon/functions';

let pool: Pool | null = null;

function getDbPool() {
  if (!pool) {
    pool = new Pool({
      connectionString: process.env.DATABASE_URL,
      max: 5
    });
    attachDatabasePool(pool);
  }
  return pool;
}

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    // 1. Scheduled Cron Route: Prune expired fleet entries and stale commands
    if (url.pathname === '/cron' || url.pathname === '/' && request.method === 'POST') {
      try {
        const db = getDbPool();

        // Mark stale devices as offline (no heartbeat in 90 seconds)
        const markRes = await db.query(`
          UPDATE fleet_devices
          SET status = 'offline'
          WHERE last_seen < NOW() - INTERVAL '90 seconds'
            AND status = 'online'
          RETURNING id, name;
        `);

        // Clean commands older than 48 hours
        const pruneRes = await db.query(`
          DELETE FROM fleet_commands
          WHERE created_at < NOW() - INTERVAL '48 hours'
          RETURNING id;
        `);

        // Clean expired realtime messages older than 24 hours
        await db.query(`
          DELETE FROM live_messages
          WHERE created_at < NOW() - INTERVAL '24 hours';
        `);

        return Response.json({
          ok: true,
          action: 'fleet_prune_success',
          stale_devices_marked_offline: markRes.rowCount,
          expired_commands_deleted: pruneRes.rowCount,
          timestamp: new Date().toISOString()
        });
      } catch (err: any) {
        return Response.json({ ok: false, error: err.message }, { status: 500 });
      }
    }

    // 2. Security & Tamper Alert Webhook Route
    if (url.pathname === '/security-alert' && request.method === 'POST') {
      try {
        const body: any = await request.json().catch(() => ({}));
        const deviceId = String(body.device_id || 'unknown').trim();
        const eventType = String(body.event || 'tamper_alert').trim();
        const details = body.details || {};

        const db = getDbPool();

        // Ensure security_events audit table exists
        await db.query(`
          CREATE TABLE IF NOT EXISTS fleet_security_events (
            id SERIAL PRIMARY KEY,
            device_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            details JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
          );
        `);

        await db.query(
          `INSERT INTO fleet_security_events (device_id, event_type, details) VALUES ($1, $2, $3);`,
          [deviceId, eventType, JSON.stringify(details)]
        );

        return Response.json({
          ok: true,
          msg: 'Security event recorded securely in 24/7 Neon Engine',
          device_id: deviceId,
          event_type: eventType,
          timestamp: new Date().toISOString()
        });
      } catch (err: any) {
        return Response.json({ ok: false, error: err.message }, { status: 500 });
      }
    }

    return Response.json({
      service: 'Project-X-Nano 24/7 Fleet Health & Security Engine',
      endpoints: ['/cron (POST/Schedule)', '/security-alert (POST)'],
      status: 'operational'
    });
  }
};
