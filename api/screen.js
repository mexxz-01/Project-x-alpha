const { getDb, initSchema } = require('./db');

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  try {
    await initSchema();
    const sql = getDb();

    // 1. GET: Fetch latest screen snapshot of target device
    if (req.method === 'GET') {
      const deviceId = String(req.query.device_id || '').trim();
      if (!deviceId) return res.status(400).json({ error: 'device_id required' });

      const rows = await sql.query(
        `SELECT device_id, image_data, updated_at
         FROM fleet_screens
         WHERE device_id = $1;`,
        [deviceId]
      );

      if (rows.length === 0) {
        return res.status(404).json({ ok: false, error: 'No screen capture available for this device yet.' });
      }

      // If requested as raw image binary
      if (req.query.raw === '1') {
        const base64Data = rows[0].image_data.replace(/^data:image\/\w+;base64,/, '');
        const buffer = Buffer.from(base64Data, 'base64');
        res.setHeader('Content-Type', 'image/jpeg');
        res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
        return res.status(200).send(buffer);
      }

      return res.status(200).json({
        ok: true,
        device_id: rows[0].device_id,
        image_data: rows[0].image_data,
        updated_at: rows[0].updated_at
      });
    }

    // 2. POST: Agent uploading screen capture
    if (req.method === 'POST') {
      const body = req.body || {};
      const deviceId = String(body.device_id || '').trim();
      const imageData = String(body.image_data || body.image || '').trim();

      if (!deviceId || !imageData) {
        return res.status(400).json({ error: 'device_id and image_data are required.' });
      }

      await sql.query(
        `INSERT INTO fleet_screens (device_id, image_data, updated_at)
         VALUES ($1, $2, NOW())
         ON CONFLICT (device_id) DO UPDATE SET
           image_data = EXCLUDED.image_data,
           updated_at = NOW();`,
        [deviceId, imageData]
      );

      return res.status(200).json({ ok: true, msg: 'Screen capture updated.' });
    }

    return res.status(405).json({ error: 'Method Not Allowed' });
  } catch (err) {
    console.error('Screen API Error:', err);
    return res.status(500).json({ ok: false, error: err.message || 'Internal Server Error' });
  }
};
