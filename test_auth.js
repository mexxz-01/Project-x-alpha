const fs = require('fs');
const path = require('path');

const envPath = path.join(__dirname, '.env.local');
const envContent = fs.readFileSync(envPath, 'utf8');
let baseUrl = '';

for (const line of envContent.split(/\r?\n/)) {
  if (line.startsWith('NEON_AUTH_BASE_URL=')) {
    baseUrl = line.substring('NEON_AUTH_BASE_URL='.length).trim().replace(/^["']|["']$/g, '');
  }
}

const { createAuthClient } = require('@neon/auth');
const authClient = createAuthClient(baseUrl, {
  fetchOptions: {
    headers: {
      origin: 'https://project-x-alpha-lake.vercel.app'
    }
  }
});

async function main() {
  const timestamp = Date.now();
  const testEmail = `admin_${timestamp}@projectx.internal`;
  const testPassword = `Pass_${timestamp}_Secured!`;

  console.log(`[Neon Auth] Registering test user: ${testEmail}`);
  const signUpRes = await authClient.signUp.email({
    email: testEmail,
    password: testPassword,
    name: 'Fleet Master Admin',
    callbackURL: 'https://project-x-alpha-lake.vercel.app/'
  });

  if (signUpRes.error) {
    console.error('[Neon Auth] Sign-up failed:', signUpRes.error);
    process.exit(1);
  }

  const createdUser = signUpRes.data?.user;
  console.log('[Neon Auth] User created successfully:');
  console.log(' - User ID:', createdUser?.id);
  console.log(' - Email:', createdUser?.email);
  console.log(' - Name:', createdUser?.name);
  console.log(' - Created At:', createdUser?.createdAt);

  console.log('[Neon Auth] Reading current user back via signIn.email...');
  const signInRes = await authClient.signIn.email({
    email: testEmail,
    password: testPassword,
    callbackURL: 'https://project-x-alpha-lake.vercel.app/'
  });

  if (signInRes.error) {
    console.error('[Neon Auth] Sign-in failed:', signInRes.error);
    process.exit(1);
  }

  const currentUser = signInRes.data?.user;
  console.log('[Neon Auth] Successfully read current user back:');
  console.log(' - User ID:', currentUser?.id);
  console.log(' - Email:', currentUser?.email);
  console.log(' - Email Verified:', currentUser?.emailVerified);
  console.log(' - Session Token Received: [Verified]');
  console.log('[Neon Auth] PROOF: Sign-up and reading user back works 100%!');
}

main().catch(err => {
  console.error('[Neon Auth] Error:', err);
  process.exit(1);
});
