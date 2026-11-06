const fs = require('fs');
const path = require('path');

module.exports = function handler(req, res) {
  // If APK is bundled in public
  const localApkPath = path.join(process.cwd(), 'public', 'Project-X-Nano.apk');
  if (fs.existsSync(localApkPath)) {
    const stat = fs.statSync(localApkPath);
    res.writeHead(200, {
      'Content-Type': 'application/vnd.android.package-archive',
      'Content-Length': stat.size,
      'Content-Disposition': 'attachment; filename="Project-X-Nano.apk"'
    });
    const readStream = fs.createReadStream(localApkPath);
    return readStream.pipe(res);
  }

  // Seamless fallback: Redirect to raw GitHub release artifact
  return res.redirect(302, 'https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/Project-X-Nano.apk');
};
