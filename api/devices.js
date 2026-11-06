const { getDb, initSchema } = require('./db');
const { setCorsHeaders, authenticateRequest } = require('./auth_util');

module.exports = async function handler(req, res) {
  setCorsHeaders(req, res);

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  try {
    await initSchema();
    const sql = getDb();

    // 1. GET: List all registered fleet devices (Protected: requires admin session)
    if (req.method === 'GET') {
      const session = authenticateRequest(req);
      if (!session) {
        return res.status(401).json({ ok: false, error: 'Authentication required to view device fleet.' });
      }

      const rows = await sql.query(`
        SELECT 
          id, name, host_url, tunnel_url, public_ip, lan_ip, port, cpu, ram, os,
          CASE 
            WHEN last_seen > NOW() - INTERVAL '90 seconds' THEN 'online'
            ELSE 'offline'
          END as status,
          last_seen, metadata
        FROM fleet_devices
        ORDER BY last_seen DESC;
      `);
      return res.status(200).json({ ok: true, count: rows.length, devices: rows });
    }

    // 2. POST: Register or Heartbeat from Host Device Agent
    if (req.method === 'POST') {
      const body = req.body || {};
      const rawHost = body.host || body.hostname || body.name || '';
      const fallbackId = rawHost ? rawHost.toLowerCase().replace(/[^a-z0-9_-]/g, '-') : ('device-' + Date.now().toString(36));
      const id = String(body.id || body.device_id || fallbackId).trim();
      const name = String(body.name || body.device_name || body.hostname || body.host || 'Unknown PC').trim();
      const host_url = String(body.host_url || body.public_url || body.url || '').trim();
      const tunnel_url = String(body.tunnel_url || body.public_url || '').trim();
      const lan_ip = String(body.lan_ip || '').trim();
      const port = Number(body.port) || 8765;
      const cpu = Number(body.cpu || (body.stats && body.stats.cpu) || 0);
      const ram = Number(body.ram || (body.stats && body.stats.ram) || (body.stats && body.stats.memory) || 0);
      const os = String(body.os || body.platform || '').trim();
      const metadata = JSON.stringify(body.metadata || body.stats || {});

      const clientIp = (req.headers['x-forwarded-for'] || req.socket?.remoteAddress || '').split(',')[0].trim();

      if (!id) {
        return res.status(400).json({ error: 'Device ID is required.' });
      }

      const activeUrl = tunnel_url || host_url || 'cloud-managed';

      await sql.query(
        `
        INSERT INTO fleet_devices (id, name, host_url, tunnel_url, public_ip, lan_ip, port, cpu, ram, os, status, last_seen, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'online', NOW(), $11::jsonb)
        ON CONFLICT (id) DO UPDATE SET
          name = EXCLUDED.name,
          host_url = COALESCE(NULLIF(EXCLUDED.host_url, ''), fleet_devices.host_url),
          tunnel_url = COALESCE(NULLIF(EXCLUDED.tunnel_url, ''), fleet_devices.tunnel_url),
          public_ip = EXCLUDED.public_ip,
          lan_ip = EXCLUDED.lan_ip,
          port = EXCLUDED.port,
          cpu = EXCLUDED.cpu,
          ram = EXCLUDED.ram,
          os = EXCLUDED.os,
          status = 'online',
          last_seen = NOW(),
          metadata = EXCLUDED.metadata;
      `,
        [id, name, activeUrl, tunnel_url, clientIp, lan_ip, port, cpu, ram, os, metadata]
      );

      return res.status(200).json({ ok: true, msg: `Heartbeat registered for ${name}`, id });
    }

    // 3. DELETE: Remove device from cloud coordinator (Protected: requires admin session)
    if (req.method === 'DELETE') {
      const session = authenticateRequest(req);
      if (!session) {
        return res.status(401).json({ ok: false, error: 'Authentication required to delete a device.' });
      }

      const id = String(req.query.id || (req.body && req.body.id) || '').trim();
      if (!id) return res.status(400).json({ error: 'Device ID required.' });
      await sql.query(`DELETE FROM fleet_devices WHERE id = $1;`, [id]);
      return res.status(200).json({ ok: true, msg: 'Device removed from fleet registry.' });
    }

    return res.status(405).json({ error: 'Method Not Allowed' });
  } catch (err) {
    console.error('API Error:', err.message);
    return res.status(500).json({ ok: false, error: 'Internal server error while processing devices.' });
  }
};
