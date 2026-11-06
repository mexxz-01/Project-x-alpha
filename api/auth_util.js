const crypto = require('crypto');

// Auth configuration
const COOKIE_NAME = 'pxn_session';
const SESSION_MAX_AGE_SEC = 30 * 24 * 3600; // 30 days

// Secret key for HMAC signing tokens
function getSecretKey() {
  return process.env.SECRET_KEY || process.env.NEON_REALTIME_SECRET || 'pxn_secure_edge_hmac_secret_key_32chars_min';
}

// Trusted origins for CORS
const ALLOWED_ORIGIN_PATTERNS = [
  /^https:\/\/[a-zA-Z0-9-]+\.vercel\.app$/,
  /^https:\/\/[a-zA-Z0-9-]+\.trycloudflare\.com$/,
  /^http:\/\/localhost:\d+$/,
  /^http:\/\/127\.0\.0\.1:\d+$/
];

function isOriginAllowed(origin) {
  if (!origin) return false;
  return ALLOWED_ORIGIN_PATTERNS.some(p => p.test(origin));
}

function setCorsHeaders(req, res) {
  const origin = req.headers.origin;
  if (origin && isOriginAllowed(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Access-Control-Allow-Credentials', 'true');
  } else {
    // If not in allowed list, do not reflect back wildcard with credentials
    res.setHeader('Access-Control-Allow-Origin', 'null');
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-CSRF-Token');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
}

// Mint cryptographically signed tamper-proof session token
function mintSessionToken(role = 'admin') {
  const payload = {
    role,
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + SESSION_MAX_AGE_SEC,
    nonce: crypto.randomBytes(16).toString('hex')
  };
  const data = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const sig = crypto.createHmac('sha256', getSecretKey()).update(data).digest('base64url');
  return `${data}.${sig}`;
}

// Verify signed session token
function verifySessionToken(token) {
  if (!token || typeof token !== 'string') return null;
  const parts = token.split('.');
  if (parts.length !== 2) return null;
  const [data, sig] = parts;
  try {
    const expectedSig = crypto.createHmac('sha256', getSecretKey()).update(data).digest('base64url');
    if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expectedSig))) {
      return null;
    }
    const payload = JSON.parse(Buffer.from(data, 'base64url').toString('utf-8'));
    if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) {
      return null;
    }
    return payload;
  } catch (err) {
    return null;
  }
}

// Parse cookies from request header
function parseCookies(req) {
  const list = {};
  const cookieHeader = req.headers.cookie;
  if (!cookieHeader) return list;
  cookieHeader.split(';').forEach(cookie => {
    let [name, ...rest] = cookie.split('=');
    name = name?.trim();
    if (!name) return;
    const value = rest.join('=').trim();
    list[name] = decodeURIComponent(value);
  });
  return list;
}

// Authenticate request via Cookie or Authorization: Bearer
function authenticateRequest(req) {
  // 1. Check HttpOnly cookie
  const cookies = parseCookies(req);
  if (cookies[COOKIE_NAME]) {
    const session = verifySessionToken(cookies[COOKIE_NAME]);
    if (session) return session;
  }

  // 2. Check Authorization Bearer header
  const authHeader = req.headers.authorization;
  if (authHeader && authHeader.toLowerCase().startsWith('bearer ')) {
    const rawToken = authHeader.substring(7).trim();
    const session = verifySessionToken(rawToken);
    if (session) return session;
  }

  return null;
}

// In-memory rate limiting map: ip -> { count, resetTime }
const RATE_LIMIT_MAP = new Map();
function checkRateLimit(ip, maxAttempts = 10, windowMs = 60000) {
  const now = Date.now();
  const entry = RATE_LIMIT_MAP.get(ip) || { count: 0, resetTime: now + windowMs };
  if (now > entry.resetTime) {
    entry.count = 1;
    entry.resetTime = now + windowMs;
  } else {
    entry.count++;
  }
  RATE_LIMIT_MAP.set(ip, entry);
  return entry.count <= maxAttempts;
}

module.exports = {
  COOKIE_NAME,
  SESSION_MAX_AGE_SEC,
  setCorsHeaders,
  mintSessionToken,
  verifySessionToken,
  authenticateRequest,
  checkRateLimit
};
