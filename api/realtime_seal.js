const { createRealtime, rawSql } = require('@neon/realtime/server');

let realtimeInstance = null;

function getRealtime() {
  if (!realtimeInstance) {
    const secret = process.env.NEON_REALTIME_SECRET;
    const url = process.env.NEON_REALTIME_URL;
    const dbUrl = process.env.DATABASE_URL;
    const dbMatch = dbUrl ? dbUrl.match(/\/([^\/?]+)(\?|$)/) : null;
    const dbName = dbMatch ? dbMatch[1] : 'neondb';

    realtimeInstance = createRealtime({
      secret: secret,
      db: dbName,
      url: url,
    });
  }
  return realtimeInstance;
}

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  try {
    const rt = getRealtime();

    // Seal the query for live messages table
    const query = rawSql(
      'SELECT id, message, created_at FROM live_messages ORDER BY id DESC LIMIT 20'
    );

    const sealed = await rt.seal({ query });

    return res.status(200).json({
      ok: true,
      sealed: sealed,
      realtime_url: process.env.NEON_REALTIME_URL,
    });
  } catch (err) {
    console.error('Realtime Seal API Error:', err);
    return res.status(500).json({ ok: false, error: err.message });
  }
};
