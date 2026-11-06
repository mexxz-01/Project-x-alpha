const { getDb, initSchema } = require('./db');

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  try {
    await initSchema();
    const sql = getDb();

    // 1. GET: List all registered fleet devices and mark offline if heartbeat expired (> 90s)
    if (req.method === 'GET') {
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

    // 2. POST: Register or Heartbeat from Host Device
    if (req.method === 'POST') {
      const body = req.body || {};
      // Fallback: If id is omitted (e.g. from setup.ps1 or curl reporting), derive id from host name or generate one
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

      const clientIp = req.headers['x-forwarded-for'] || req.socket.remoteAddress || '';

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

    // 3. DELETE: Remove device from cloud coordinator
    if (req.method === 'DELETE') {
      const id = String(req.query.id || (req.body && req.body.id) || '').trim();
      if (!id) return res.status(400).json({ error: 'Device ID required.' });
      await sql.query(`DELETE FROM fleet_devices WHERE id = $1;`, [id]);
      return res.status(200).json({ ok: true, msg: 'Device removed from fleet registry.' });
    }

    return res.status(405).json({ error: 'Method Not Allowed' });
  } catch (err) {
    console.error('API Error:', err);
    return res.status(500).json({ ok: false, error: err.message || 'Internal Server Error' });
  }
};
