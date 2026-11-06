const { neon } = require('@neondatabase/serverless');

function getDb() {
  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) {
    throw new Error('DATABASE_URL environment variable is not defined.');
  }
  return neon(connectionString);
}

let schemaInitialized = false;

async function initSchema() {
  if (schemaInitialized) return;
  const sql = getDb();
  await sql.query(`
    CREATE TABLE IF NOT EXISTS fleet_devices (
      id VARCHAR(64) PRIMARY KEY,
      name VARCHAR(255) NOT NULL,
      host_url TEXT,
      tunnel_url TEXT,
      public_ip VARCHAR(64),
      lan_ip VARCHAR(64),
      port INT DEFAULT 8765,
      cpu NUMERIC(5, 2) DEFAULT 0,
      ram NUMERIC(5, 2) DEFAULT 0,
      os VARCHAR(255),
      status VARCHAR(32) DEFAULT 'online',
      last_seen TIMESTAMPTZ DEFAULT NOW(),
      metadata JSONB DEFAULT '{}'::jsonb
    );
  `);

  await sql.query(`
    CREATE TABLE IF NOT EXISTS fleet_commands (
      id VARCHAR(64) PRIMARY KEY,
      device_id VARCHAR(64) NOT NULL,
      command VARCHAR(64) NOT NULL,
      payload JSONB DEFAULT '{}'::jsonb,
      status VARCHAR(32) DEFAULT 'pending',
      result JSONB DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      completed_at TIMESTAMPTZ
    );
  `);

  await sql.query(`
    CREATE TABLE IF NOT EXISTS fleet_screens (
      device_id VARCHAR(64) PRIMARY KEY,
      image_data TEXT NOT NULL,
      updated_at TIMESTAMPTZ DEFAULT NOW()
    );
  `);
  schemaInitialized = true;
}

module.exports = { getDb, initSchema };
