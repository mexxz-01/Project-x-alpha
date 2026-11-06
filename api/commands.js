const { getDb, initSchema } = require('./db');
const crypto = require('crypto');

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

    // 1. GET: Poll pending command (for PC agent) or check command status (for UI)
    if (req.method === 'GET') {
      const deviceId = String(req.query.device_id || '').trim();
      const commandId = String(req.query.id || req.query.command_id || '').trim();
      const isPoll = req.query.poll === '1' || req.query.poll === 'true';

      // Agent polling for next work item
      if (isPoll && deviceId) {
        const rows = await sql.query(
          `SELECT id, device_id, command, payload, status, created_at
           FROM fleet_commands
           WHERE device_id = $1 AND status = 'pending'
           ORDER BY created_at ASC
           LIMIT 1;`,
          [deviceId]
        );

        if (rows.length > 0) {
          const cmd = rows[0];
          await sql.query(
            `UPDATE fleet_commands SET status = 'running' WHERE id = $1;`,
            [cmd.id]
          );
          return res.status(200).json({ ok: true, command: cmd });
        }
        return res.status(200).json({ ok: true, command: null });
      }

      // Query single command status (for UI wait)
      if (commandId) {
        const rows = await sql.query(
          `SELECT id, device_id, command, payload, status, result, created_at, completed_at
           FROM fleet_commands
           WHERE id = $1;`,
          [commandId]
        );
        if (rows.length === 0) {
          return res.status(404).json({ ok: false, error: 'Command not found' });
        }
        return res.status(200).json({ ok: true, command: rows[0] });
      }

      // List recent commands for a device
      if (deviceId) {
        const rows = await sql.query(
          `SELECT id, device_id, command, status, created_at, completed_at
           FROM fleet_commands
           WHERE device_id = $1
           ORDER BY created_at DESC
           LIMIT 25;`,
          [deviceId]
        );
        return res.status(200).json({ ok: true, commands: rows });
      }

      return res.status(400).json({ error: 'device_id or id parameter required.' });
    }

    // 2. POST: Queue a new command (from UI) or return execution result (from PC Agent)
    if (req.method === 'POST') {
      const body = req.body || {};

      // A: Agent returning execution result
      if (body.action === 'result' || (body.command_id && (body.result !== undefined || body.error !== undefined))) {
        const cmdId = String(body.command_id || body.id || '').trim();
        const status = body.status === 'failed' || body.error ? 'failed' : 'completed';
        const resultPayload = JSON.stringify(body.result || { output: body.output, error: body.error } || {});

        if (!cmdId) return res.status(400).json({ error: 'command_id is required' });

        await sql.query(
          `UPDATE fleet_commands
           SET status = $1, result = $2::jsonb, completed_at = NOW()
           WHERE id = $3;`,
          [status, resultPayload, cmdId]
        );

        return res.status(200).json({ ok: true, msg: 'Execution result saved.' });
      }

      // B: Queue new command for a remote PC
      const deviceId = String(body.device_id || body.target || '').trim();
      const command = String(body.command || body.action || '').trim().toLowerCase();
      const payload = JSON.stringify(body.payload || body.args || {});

      if (!deviceId || !command) {
        return res.status(400).json({ error: 'device_id and command are required.' });
      }

      const cmdId = 'cmd_' + crypto.randomBytes(8).toString('hex');

      await sql.query(
        `INSERT INTO fleet_commands (id, device_id, command, payload, status, created_at)
         VALUES ($1, $2, $3, $4::jsonb, 'pending', NOW());`,
        [cmdId, deviceId, command, payload]
      );

      return res.status(200).json({
        ok: true,
        command_id: cmdId,
        msg: `Command '${command}' queued for ${deviceId}`
      });
    }

    return res.status(405).json({ error: 'Method Not Allowed' });
  } catch (err) {
    console.error('Commands API Error:', err);
    return res.status(500).json({ ok: false, error: err.message || 'Internal Server Error' });
  }
};
