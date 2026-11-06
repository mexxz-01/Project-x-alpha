const { getDb, initSchema } = require('./db');

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  try {
    await initSchema();
    const sql = getDb();

    // Check device_id requested, or get most recently seen active device
    const deviceId = req.query.device_id || '';
    let query = `
      SELECT id, name, host_url, tunnel_url, lan_ip, port, cpu, ram, os,
             CASE 
               WHEN last_seen > NOW() - INTERVAL '90 seconds' THEN 'online'
               ELSE 'offline'
             END as status,
             last_seen, metadata
      FROM fleet_devices
    `;
    const params = [];
    if (deviceId) {
      query += ` WHERE id = $1`;
      params.push(deviceId);
    } else {
      query += ` ORDER BY last_seen DESC LIMIT 1`;
    }

    const rows = await sql.query(query, params);
    if (!rows.length) {
      return res.status(200).json({
        ok: true,
        cpu: 0,
        ram: 0,
        disk: 0,
        host: 'Cloud Hub',
        os: 'Serverless',
        uptime_min: 0,
        battery: null,
        online: false
      });
    }

    const d = rows[0];
    const meta = d.metadata || {};
    return res.status(200).json({
      ok: true,
      id: d.id,
      name: d.name,
      host: d.name,
      os: d.os || 'Windows 11/10',
      cpu: parseFloat(d.cpu) || (meta.cpu ? parseFloat(meta.cpu) : 0),
      ram: parseFloat(d.ram) || (meta.ram ? parseFloat(meta.ram) : 0),
      disk: meta.disk ? parseFloat(meta.disk) : 40,
      uptime_min: meta.boot_time ? Math.floor((Date.now() / 1000 - meta.boot_time) / 60) : 120,
      battery: meta.battery != null ? { percent: meta.battery, plugged: true } : null,
      status: d.status,
      online: d.status === 'online',
      last_seen: d.last_seen
    });
  } catch (err) {
    console.error('Stats API error:', err);
    return res.status(500).json({ error: err.message });
  }
};
