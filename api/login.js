const crypto = require('crypto');
const {
  COOKIE_NAME,
  SESSION_MAX_AGE_SEC,
  setCorsHeaders,
  mintSessionToken,
  authenticateRequest,
  checkRateLimit
} = require('./auth_util');

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
  setCorsHeaders(req, res);

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  // GET: Check active session validity
  if (req.method === 'GET') {
    const session = authenticateRequest(req);
    if (session) {
      return res.status(200).json({
        ok: true,
        authenticated: true,
        role: session.role || 'admin',
        expires_at: session.exp
      });
    }
    return res.status(401).json({
      ok: false,
      authenticated: false,
      error: 'Not authenticated'
    });
  }

  // POST: Login with rate limiting and secure HttpOnly cookie issuance
  if (req.method === 'POST') {
    const clientIp = (req.headers['x-forwarded-for'] || req.socket?.remoteAddress || '127.0.0.1').split(',')[0].trim();

    // 1. Rate limiting: max 5 login attempts per minute per IP
    if (!checkRateLimit(clientIp, 5, 60000)) {
      return res.status(429).json({
        ok: false,
        error: 'Too many authentication attempts. Please wait 60 seconds.'
      });
    }

    let body = req.body || {};
    if (typeof body === 'string') {
      try { body = JSON.parse(body); } catch(e) { body = {}; }
    }
    const pw = String(body.password || '').trim();

    if (!pw) {
      return res.status(400).json({ ok: false, error: 'Password is required' });
    }

    if (!verifyMasterPassword(pw)) {
      return res.status(401).json({ ok: false, error: 'Invalid Master Password' });
    }

    // 2. Mint signed tamper-proof token
    const token = mintSessionToken('admin');

    // 3. Set HttpOnly, Secure, SameSite=Strict cookie
    const isHttps = req.headers['x-forwarded-proto'] === 'https' || req.headers.host?.includes('vercel.app');
    const cookieOptions = [
      `${COOKIE_NAME}=${token}`,
      `Path=/`,
      `Max-Age=${SESSION_MAX_AGE_SEC}`,
      `HttpOnly`,
      `SameSite=Strict`
    ];
    if (isHttps) {
      cookieOptions.push('Secure');
    }

    res.setHeader('Set-Cookie', cookieOptions.join('; '));

    return res.status(200).json({
      ok: true,
      token,
      role: 'admin',
      msg: 'Authenticated successfully with 24/7 Cloud Hub'
    });
  }

  // DELETE: Logout by clearing session cookie
  if (req.method === 'DELETE') {
    res.setHeader('Set-Cookie', `${COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict`);
    return res.status(200).json({ ok: true, msg: 'Logged out successfully' });
  }

  return res.status(405).json({ error: 'Method Not Allowed' });
};
