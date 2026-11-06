const { getDb, initSchema } = require('./db');

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  try {
    await initSchema();
    const sql = getDb();

    const counts = await sql.query(`
      SELECT 
        COUNT(*) as total_devices,
        COUNT(*) FILTER (WHERE last_seen > NOW() - INTERVAL '90 seconds') as online_devices
      FROM fleet_devices;
    `);

    return res.status(200).json({
      ok: true,
      service: 'Project-X-Nano Central Cloud Coordinator',
      database: 'Neon Serverless Postgres',
      metrics: {
        total_registered_pcs: Number(counts[0].total_devices),
        online_pcs: Number(counts[0].online_devices),
      },
      timestamp: new Date().toISOString()
    });
  } catch (err) {
    return res.status(500).json({ ok: false, error: err.message });
  }
};
