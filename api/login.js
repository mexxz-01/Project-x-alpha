const crypto = require('crypto');

// Master password hash: scrypt:32768:8:1$w2drGdcnVxkA0z3j$bf177d84c9af8766383cc6a84e7ba5959b6c87d809d5b8eae7b180f1999a27698dc795552475125ebbec795597ee5e75b2d5a1e37ea0355f8a727e4e6a5ca50f
const STORED_SALT = 'w2drGdcnVxkA0z3j';
const STORED_HASH = 'bf177d84c9af8766383cc6a84e7ba5959b6c87d809d5b8eae7b180f1999a27698dc795552475125ebbec795597ee5e75b2d5a1e37ea0355f8a727e4e6a5ca50f';

function verifyMasterPassword(candidate) {
  if (!candidate || typeof candidate !== 'string') return false;
  try {
    const salt = Buffer.from(STORED_SALT, 'utf-8');
    const key = crypto.scryptSync(candidate, salt, 64, {
      N: 32768,
      r: 8,
      p: 1,
      maxmem: 64 * 1024 * 1024
    });
    const candidateHex = key.toString('hex');
    return crypto.timingSafeEqual(Buffer.from(candidateHex), Buffer.from(STORED_HASH));
  } catch (err) {
    return false;
  }
}

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method === 'GET') {
    return res.status(200).json({
      ok: true,
      service: 'Project-X-Nano 24/7 Neon Cloud Hub',
      auth: 'scrypt-protected'
    });
  }

  if (req.method === 'POST') {
    const body = req.body || {};
    const pw = String(body.password || '').trim();

    if (!pw) {
      return res.status(400).json({ ok: false, error: 'Password is required' });
    }

    if (!verifyMasterPassword(pw)) {
      return res.status(401).json({ ok: false, error: 'Invalid Master Password' });
    }

    // Generate authenticated session token
    const token = 'pxn_cloud_' + crypto.randomBytes(32).toString('hex');
    return res.status(200).json({
      ok: true,
      token,
      msg: 'Authenticated successfully with 24/7 Cloud Hub'
    });
  }

  return res.status(405).json({ error: 'Method Not Allowed' });
};
