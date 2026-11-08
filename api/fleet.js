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

    // 1. GET: Return fleet list for frontend Fleet tab
    if (req.method === 'GET') {
      const session = authenticateRequest(req);
      if (!session) {
        return res.status(401).json({ ok: false, error: 'Authentication required to view fleet nodes.' });
      }

      const rows = await sql.query(`
        SELECT 
          id, name, host_url, tunnel_url, public_ip, lan_ip, port, cpu, ram, os,
          CASE 
            WHEN last_seen > NOW() - INTERVAL '90 seconds' THEN true
            ELSE false
          END as online,
          last_seen, metadata
        FROM fleet_devices
        ORDER BY last_seen DESC;
      `);

      const fleet = rows.map(r => ({
        id: r.id,
        name: r.name,
        url: r.tunnel_url || r.host_url || (`http://${r.lan_ip}:${r.port}`),
        host_url: r.host_url,
        tunnel_url: r.tunnel_url,
        online: r.online,
        status: r.online ? 'online' : 'offline',
        cpu: r.cpu,
        ram: r.ram,
        os: r.os,
        lan_ip: r.lan_ip,
        public_ip: r.public_ip,
        last_seen: r.last_seen,
        local: false
      }));

      return res.status(200).json({ ok: true, count: fleet.length, fleet });
    }

    // 2. POST: Add or Remove fleet node
    if (req.method === 'POST') {
      const session = authenticateRequest(req);
      if (!session) {
        return res.status(401).json({ ok: false, error: 'Authentication required to manage fleet nodes.' });
      }

      const body = req.body || {};
      const action = body.action || req.query.action || '';

      if (action === 'remove' || body.id && !body.url) {
        const id = String(body.id || '').trim();
        if (!id) return res.status(400).json({ error: 'Device ID required.' });
        await sql.query(`DELETE FROM fleet_devices WHERE id = $1;`, [id]);
        return res.status(200).json({ ok: true, msg: 'Device removed from fleet registry.' });
      }

      // Add node
      const name = String(body.name || 'Remote PC').trim();
      const url = String(body.url || '').trim();
      if (!url) return res.status(400).json({ error: 'Device URL required.' });

      const id = 'pc_' + Buffer.from(name + url).toString('hex').slice(0, 8);
      await sql.query(`
        INSERT INTO fleet_devices (id, name, host_url, tunnel_url, port, status, last_seen)
        VALUES ($1, $2, $3, $3, 8765, 'online', NOW())
        ON CONFLICT (id) DO UPDATE SET
          name = EXCLUDED.name,
          host_url = EXCLUDED.host_url,
          tunnel_url = EXCLUDED.tunnel_url,
          last_seen = NOW();
      `, [id, name, url]);

      return res.status(200).json({ ok: true, msg: `Added ${name} to fleet.`, id });
    }

    return res.status(405).json({ error: 'Method Not Allowed' });
  } catch (err) {
    console.error('Fleet API Error:', err.message);
    return res.status(500).json({ ok: false, error: 'Internal server error in fleet API.' });
  }
};
