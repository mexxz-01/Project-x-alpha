const http = require('http');
const https = require('https');
const crypto = require('crypto');

// Load environment variables from .env.local
const fs = require('fs');
const env = fs.readFileSync('.env.local', 'utf-8');
for (const line of env.split(/\r?\n/)) {
  const m = line.match(/^([^=]+)=(.*)$/);
  if (m) process.env[m[1].trim()] = m[2].trim().replace(/^['"]|['"]$/g, '');
}

const {
  mintSessionToken,
  verifySessionToken,
  authenticateRequest
} = require('./api/auth_util');

async function runTestSuite() {
  console.log('=== RUNNING SECURITY AUDIT VERIFICATION SUITE ===\n');

  // Test 1: Session Token Minting & Verification
  console.log('[Test 1] Session token generation & signature integrity...');
  const token = mintSessionToken('admin');
  const verified = verifySessionToken(token);
  if (!verified || verified.role !== 'admin') {
    throw new Error('Test 1 Failed: Token failed cryptographic signature verification');
  }
  console.log('  ✔ Passed: Cryptographically signed token verified successfully (Role: ' + verified.role + ')');

  // Test 2: Tampered Token Detection
  console.log('[Test 2] Tampered token rejection...');
  const tampered = token.substring(0, token.length - 4) + 'abcd';
  const tamperedResult = verifySessionToken(tampered);
  if (tamperedResult !== null) {
    throw new Error('Test 2 Failed: Tampered token was mistakenly accepted!');
  }
  console.log('  ✔ Passed: Tampered token immediately rejected by HMAC-SHA256 signature check');

  // Test 3: Unauthenticated Access to Protected Endpoints (Stats API)
  console.log('[Test 3] Rejecting unauthenticated access to /api/stats...');
  const statsHandler = require('./api/stats');
  let statsStatus = 0;
  let statsBody = null;
  const mockRes = {
    setHeader: () => {},
    status: (code) => {
      statsStatus = code;
      return { json: (data) => { statsBody = data; return mockRes; }, end: () => mockRes };
    }
  };
  await statsHandler({ method: 'GET', headers: {}, query: {} }, mockRes);
  if (statsStatus !== 401) {
    throw new Error(`Test 3 Failed: /api/stats allowed unauthenticated access (status: ${statsStatus})`);
  }
  console.log('  ✔ Passed: Unauthenticated request to /api/stats blocked with HTTP 401 (' + statsBody.error + ')');

  // Test 4: Authenticated Access to Protected Endpoints
  console.log('[Test 4] Authorizing authenticated request with Bearer session token...');
  await statsHandler({
    method: 'GET',
    headers: { authorization: `Bearer ${token}` },
    query: {}
  }, mockRes);
  if (statsStatus !== 200 || !statsBody.ok) {
    throw new Error(`Test 4 Failed: Valid session rejected (status: ${statsStatus})`);
  }
  console.log('  ✔ Passed: Authenticated session granted access to telemetry data');

  // Test 5: Unauthenticated Access to Devices API
  console.log('[Test 5] Rejecting unauthenticated access to /api/devices (GET)...');
  const devicesHandler = require('./api/devices');
  let devStatus = 0;
  let devBody = null;
  const devMockRes = {
    setHeader: () => {},
    status: (c) => {
      devStatus = c;
      return { json: (d) => { devBody = d; return devMockRes; }, end: () => devMockRes };
    }
  };
  await devicesHandler({ method: 'GET', headers: {}, query: {} }, devMockRes);
  if (devStatus !== 401) {
    throw new Error(`Test 5 Failed: /api/devices allowed unauthenticated access (status: ${devStatus})`);
  }
  console.log('  ✔ Passed: Unauthenticated request to /api/devices blocked with HTTP 401 (' + devBody.error + ')');

  // Test 6: Unauthenticated Access to Command Queue (POST /api/commands)
  console.log('[Test 6] Rejecting unauthenticated remote command trigger (POST /api/commands)...');
  const commandsHandler = require('./api/commands');
  let cmdStatus = 0;
  let cmdBody = null;
  const cmdMockRes = {
    setHeader: () => {},
    status: (c) => {
      cmdStatus = c;
      return { json: (d) => { cmdBody = d; return cmdMockRes; }, end: () => cmdMockRes };
    }
  };
  await commandsHandler({
    method: 'POST',
    headers: {},
    body: { device_id: 'test-pc', command: 'terminal', payload: { cmd: 'whoami' } }
  }, cmdMockRes);
  if (cmdStatus !== 401) {
    throw new Error(`Test 6 Failed: Remote execution allowed without authentication (status: ${cmdStatus})`);
  }
  console.log('  ✔ Passed: Remote command trigger blocked with HTTP 401 (' + cmdBody.error + ')');

  // Test 7: Unauthenticated Broadcast Command (POST /api/broadcast)
  console.log('[Test 7] Rejecting unauthenticated fleet broadcast...');
  const broadcastHandler = require('./api/broadcast');
  let bcastStatus = 0;
  let bcastBody = null;
  const bcastMockRes = {
    setHeader: () => {},
    status: (c) => {
      bcastStatus = c;
      return { json: (d) => { bcastBody = d; return bcastMockRes; }, end: () => bcastMockRes };
    }
  };
  await broadcastHandler({
    method: 'POST',
    headers: {},
    body: { command: 'terminal', payload: { cmd: 'calc.exe' } }
  }, bcastMockRes);
  if (bcastStatus !== 401) {
    throw new Error(`Test 7 Failed: Fleet broadcast allowed without authentication (status: ${bcastStatus})`);
  }
  console.log('  ✔ Passed: Fleet broadcast blocked with HTTP 401 (' + bcastBody.error + ')');

  // Test 8: Invalid Credentials on Login
  console.log('[Test 8] Rejecting invalid password on /api/login...');
  const loginHandler = require('./api/login');
  let loginStatus = 0;
  let loginBody = null;
  const loginMockRes = {
    setHeader: () => {},
    status: (c) => {
      loginStatus = c;
      return { json: (d) => { loginBody = d; return loginMockRes; }, end: () => loginMockRes };
    }
  };
  await loginHandler({
    method: 'POST',
    headers: { 'x-forwarded-for': '192.168.1.100' },
    body: { password: 'wrong-password-123' }
  }, loginMockRes);
  if (loginStatus !== 401) {
    throw new Error(`Test 8 Failed: Wrong password allowed login (status: ${loginStatus})`);
  }
  console.log('  ✔ Passed: Invalid password rejected with HTTP 401 (' + loginBody.error + ')');

  // Test 9: Valid Master Password on Login
  console.log('[Test 9] Authorizing valid Master Password on /api/login...');
  let setCookieHeader = '';
  const loginSuccessMockRes = {
    setHeader: (name, val) => {
      if (name.toLowerCase() === 'set-cookie') setCookieHeader = val;
    },
    status: (c) => {
      loginStatus = c;
      return { json: (d) => { loginBody = d; return loginSuccessMockRes; }, end: () => loginSuccessMockRes };
    }
  };
  await loginHandler({
    method: 'POST',
    headers: { 'x-forwarded-for': '192.168.1.100', 'x-forwarded-proto': 'https' },
    body: { password: 'mexxzlyn@123' }
  }, loginSuccessMockRes);
  if (loginStatus !== 200 || !loginBody.ok || !loginBody.token) {
    throw new Error(`Test 9 Failed: Valid password rejected (status: ${loginStatus})`);
  }
  if (!setCookieHeader.includes('HttpOnly') || !setCookieHeader.includes('SameSite=Strict') || !setCookieHeader.includes('Secure')) {
    throw new Error(`Test 9 Failed: Missing HttpOnly/SameSite/Secure attributes on cookie: ${setCookieHeader}`);
  }
  console.log('  ✔ Passed: Master password verified via scrypt and secure HttpOnly cookie issued');

  // Test 10: Rate Limiting Enforcement on Login
  console.log('[Test 10] Testing rate limiting on brute force login attempts...');
  let rateLimited = false;
  for (let i = 0; i < 7; i++) {
    await loginHandler({
      method: 'POST',
      headers: { 'x-forwarded-for': '10.0.0.99' },
      body: { password: 'guess-' + i }
    }, loginMockRes);
    if (loginStatus === 429) {
      rateLimited = true;
      break;
    }
  }
  if (!rateLimited) {
    throw new Error('Test 10 Failed: Brute force login attempts were not rate-limited (HTTP 429 expected)');
  }
  console.log('  ✔ Passed: Brute-force threshold exceeded and blocked with HTTP 429');

  console.log('\n======================================================');
  console.log('ALL 10 SECURITY AUDIT TESTS PASSED SUCCESSFULLY! 100%');
  console.log('======================================================');
}

runTestSuite().catch(err => {
  console.error('\n❌ Test Suite Failed:', err.message);
  process.exit(1);
});
