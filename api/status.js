const { getDb, initSchema } = require('./db');
const { setCorsHeaders } = require('./auth_util');

module.exports = async function handler(req, res) {
  setCorsHeaders(req, res);

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method Not Allowed' });
  }

  try {
    await initSchema();
    const sql = getDb();

    // Query status without leaking internal server/network architecture
    const counts = await sql.query(`
      SELECT 
        COUNT(*) as total_devices,
        COUNT(*) FILTER (WHERE last_seen > NOW() - INTERVAL '90 seconds') as online_devices
      FROM fleet_devices;
    `);

    return res.status(200).json({
      ok: true,
      service: 'Project-X-Nano Central Cloud Coordinator',
      status: 'operational',
      metrics: {
        total_registered_pcs: Number(counts[0].total_devices),
        online_pcs: Number(counts[0].online_devices),
      },
      timestamp: new Date().toISOString()
    });
  } catch (err) {
    console.error('Status error:', err.message);
    return res.status(500).json({ ok: false, error: 'Database service unavailable.' });
  }
};
