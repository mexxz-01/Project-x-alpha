const { createRealtime, rawSql } = require('@neon/realtime/server');
const { getDb } = require('./api/db');
require('dotenv').config({ path: '.env.local' });

async function run() {
  console.log('1. Initializing Neon Realtime Client...');
  const secret = process.env.NEON_REALTIME_SECRET;
  const realtimeUrl = process.env.NEON_REALTIME_URL;
  const dbUrl = process.env.DATABASE_URL;

  const dbMatch = dbUrl.match(/\/([^\/?]+)(\?|$)/);
  const dbName = dbMatch ? dbMatch[1] : 'neondb';

  const realtime = createRealtime({
    secret: secret,
    db: dbName,
    url: realtimeUrl,
  });

  const query = rawSql(
    'SELECT id, message, created_at FROM live_messages ORDER BY id DESC LIMIT 10'
  );

  console.log('2. Sealing Live SQL Query...');
  const sealed = await realtime.seal({ query });
  console.log('Query sealed successfully.');

  console.log('3. Subscribing via onChange listener...');
  const testPayload = 'Realtime-Verification-' + Date.now();
  let received = false;

  const sub = await realtime.subscribe(query);

  sub.onChange((snapshot) => {
    console.log(`[Realtime onChange Status]: ${snapshot.status}, Data items: ${snapshot.data ? snapshot.data.length : 0}`);
    if (snapshot.data) {
      const match = snapshot.data.find(r => r.message === testPayload);
      if (match) {
        console.log('🎯 Realtime change received!');
        console.log('   Row ID:', match.id);
        console.log('   Message:', match.message);
        received = true;
      }
    }
  });

  // Wait 1.5s for initial connection
  await new Promise(r => setTimeout(r, 1500));

  console.log('4. Performing Database Mutation (INSERT)...');
  const sql = getDb();
  const insertRes = await sql.query(
    'INSERT INTO live_messages (message) VALUES ($1) RETURNING id, message, created_at;',
    [testPayload]
  );
  console.log('Inserted Row:', insertRes[0]);

  // Wait up to 6 seconds for the live update to arrive
  for (let i = 0; i < 12; i++) {
    if (received) break;
    await new Promise(r => setTimeout(r, 500));
  }

  sub.unsubscribe();
  realtime.close();

  if (received) {
    console.log('==============================================');
    console.log('✅ NEON REALTIME LIVE QUERY PROVEN WORKING!');
    console.log('==============================================');
    process.exit(0);
  } else {
    console.error('❌ Realtime event did not arrive in time.');
    process.exit(1);
  }
}

run().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
