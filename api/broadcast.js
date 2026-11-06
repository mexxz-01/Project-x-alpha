const { getDb } = require('./db');
const { setCorsHeaders, authenticateRequest } = require('./auth_util');

module.exports = async function handler(req, res) {
  setCorsHeaders(req, res);

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method Not Allowed' });
  }

  // Enforce server-side authentication for fleet-wide broadcast commands
  const session = authenticateRequest(req);
  if (!session) {
    return res.status(401).json({ ok: false, error: 'Unauthorized: Authentication required to broadcast commands to fleet.' });
  }

  try {
    const body = req.body || {};
    const command = String(body.command || body.action || 'terminal').trim().toLowerCase();
    const cmdPayload = body.payload || { cmd: body.cmd || '' };

    if (command === 'terminal' && (!cmdPayload.cmd || !String(cmdPayload.cmd).trim())) {
      return res.status(400).json({ error: 'Command string is required for terminal broadcast.' });
    }

    const sql = getDb();
    
    // Fetch all active online devices (last seen within 3 minutes)
    const devices = await sql.query(`
      SELECT id, name, last_seen
      FROM fleet_devices
      WHERE last_seen > NOW() - INTERVAL '3 minutes';
    `);

    if (!devices.length) {
      return res.status(200).json({
        ok: true,
        broadcast_count: 0,
        message: 'No active online PCs connected to broadcast to.'
      });
    }

    const queued = [];
    for (const dev of devices) {
      const cmdId = 'bcast_' + Math.random().toString(36).substring(2, 10);
      await sql.query(
        `INSERT INTO fleet_commands (id, device_id, command, payload, status, created_at)
         VALUES ($1, $2, $3, $4::jsonb, 'pending', NOW());`,
        [cmdId, dev.id, command, JSON.stringify(cmdPayload)]
      );
      queued.push({ id: cmdId, device_id: dev.id, name: dev.name });
    }

    return res.status(200).json({
      ok: true,
      broadcast_count: queued.length,
      message: `Broadcasted command '${command}' to ${queued.length} active PC(s)`,
      queued
    });
  } catch (err) {
    console.error('Broadcast Error:', err.message);
    return res.status(500).json({ ok: false, error: 'Failed to broadcast command.' });
  }
};
