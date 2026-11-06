package com.remotepc.controller;

import android.animation.ObjectAnimator;
import android.animation.ValueAnimator;
import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Vibrator;
import android.view.MotionEvent;
import android.view.View;
import android.view.animation.OvershootInterpolator;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import android.app.AlertDialog;
import android.content.DialogInterface;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends Activity {

    private static final String PREFS_NAME = "RemotePC_Prefs";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String KEY_PASSWORD = "password";
    private static final String KEY_SAVED_DEVICES = "saved_devices_json";

    private WebView webView;
    private View setupView;
    private View mainCard;
    private ProgressBar progressBar;
    private EditText editServerUrl;
    private EditText editPassword;
    private TextView txtAppTitle;
    private TextView txtBackendStatus;
    private View statusDot;
    private View topBar;
    private Button btnFloatingRestore;
    private View splashOverlay;
    private View splashIcon;
    private View splashContainer;

    private SharedPreferences prefs;
    private Vibrator vibrator;

    private String currentServer = "";
    private String currentPassword = "";
    private long lastBackPressTime = 0;
    private boolean isFullscreenActive = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        applyStickyImmersiveMode();

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        vibrator = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);

        // Bind layout views
        topBar = findViewById(R.id.topBar);
        statusDot = findViewById(R.id.statusDot);
        txtAppTitle = findViewById(R.id.txtAppTitle);
        txtBackendStatus = findViewById(R.id.txtBackendStatus);
        progressBar = findViewById(R.id.progressBar);
        webView = findViewById(R.id.webView);
        setupView = findViewById(R.id.setupView);
        mainCard = findViewById(R.id.mainCard);
        btnFloatingRestore = findViewById(R.id.btnFloatingRestore);

        editServerUrl = findViewById(R.id.editServerUrl);
        editPassword = findViewById(R.id.editPassword);

        // Buttons
        Button btnFullscreen = findViewById(R.id.btnFullscreen);
        Button btnQuickLock = findViewById(R.id.btnQuickLock);
        Button btnSwitchPC = findViewById(R.id.btnSwitchPC);
        Button btnRefresh = findViewById(R.id.btnRefresh);
        Button btnConnect = findViewById(R.id.btnConnect);
        Button btnTestPing = findViewById(R.id.btnTestPing);
        Button btnSaveConfig = findViewById(R.id.btnSaveConfig);

        Button presetHotspot = findViewById(R.id.presetHotspot);
        Button presetLan = findViewById(R.id.presetLan);
        Button presetCloud = findViewById(R.id.presetCloud);

        // Splash Views
        splashOverlay = findViewById(R.id.splashOverlay);
        splashIcon = findViewById(R.id.splashIcon);
        splashContainer = findViewById(R.id.splashContainer);

        // Attach tactile click feedback animations
        attachClickAnimation(btnConnect);
        attachClickAnimation(btnTestPing);
        attachClickAnimation(btnSaveConfig);
        attachClickAnimation(btnQuickLock);
        attachClickAnimation(btnSwitchPC);
        attachClickAnimation(btnRefresh);
        attachClickAnimation(btnFullscreen);
        attachClickAnimation(presetHotspot);
        attachClickAnimation(presetLan);
        attachClickAnimation(presetCloud);
        attachClickAnimation(btnFloatingRestore);

        initWebView();
        startStatusPulse();

        // Load saved host configuration
        currentServer = prefs.getString(KEY_SERVER_URL, "");
        currentPassword = prefs.getString(KEY_PASSWORD, "");

        if (!currentServer.isEmpty()) {
            editServerUrl.setText(currentServer);
        }
        if (!currentPassword.isEmpty()) {
            editPassword.setText(currentPassword);
        }

        // Setup Preset Click Handlers
        presetHotspot.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                editServerUrl.setText("http://192.168.137.1:8765");
                vibrateBrief(30);
                testBackendPing("http://192.168.137.1:8765");
            }
        });

        presetLan.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                String existing = editServerUrl.getText().toString().trim();
                if (!existing.contains("192.168.1.") && !existing.contains("192.168.0.")) {
                    editServerUrl.setText("http://192.168.1.100:8765");
                }
                editServerUrl.requestFocus();
                vibrateBrief(30);
                Toast.makeText(MainActivity.this, "Set to Wi-Fi LAN IP & port 8765", Toast.LENGTH_SHORT).show();
            }
        });

        presetCloud.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                editServerUrl.setText("https://");
                editServerUrl.requestFocus();
                editServerUrl.setSelection(editServerUrl.getText().length());
                vibrateBrief(30);
                Toast.makeText(MainActivity.this, "Enter your Cloudflare / Ngrok tunnel URL", Toast.LENGTH_SHORT).show();
            }
        });

        // Top Bar Action Buttons
        btnFullscreen.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                toggleInAppFullscreen(true);
            }
        });

        btnFloatingRestore.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                toggleInAppFullscreen(false);
            }
        });

        btnSwitchPC.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showDeviceSelectorDialog();
            }
        });

        btnRefresh.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (webView.getVisibility() == View.VISIBLE) {
                    webView.reload();
                    Toast.makeText(MainActivity.this, "Reloading Controller...", Toast.LENGTH_SHORT).show();
                } else if (!currentServer.isEmpty()) {
                    loadServer(currentServer);
                }
            }
        });

        btnQuickLock.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                quickLockPC();
            }
        });

        // Card Buttons
        btnConnect.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                connectToServer();
            }
        });

        btnTestPing.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                String url = getSanitizedUrl(editServerUrl.getText().toString().trim());
                if (url.isEmpty()) {
                    Toast.makeText(MainActivity.this, "Enter backend URL first", Toast.LENGTH_SHORT).show();
                    return;
                }
                testBackendPing(url);
            }
        });

        btnSaveConfig.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                saveConfiguration();
                Toast.makeText(MainActivity.this, "Host configuration saved!", Toast.LENGTH_SHORT).show();
                vibrateBrief(40);
            }
        });

        // Start Opening Launch Animation
        startOpeningAnimation();
    }

    /**
     * Auto-Hiding System Navigation Bar and Status Bar (Immersive Sticky Mode).
     * Navigation bar auto-hides; swiping from screen edges temporarily shows it and hides again.
     */
    private void applyStickyImmersiveMode() {
        View decorView = getWindow().getDecorView();
        decorView.setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                        | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
        );
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            applyStickyImmersiveMode();
        }
    }

    /**
     * Animated Opening Launch Sequence:
     * Logo scales up with overshoot interpolator, status fades in,
     * and overlay smoothly transitions to reveal the app frontend.
     */
    private void startOpeningAnimation() {
        splashIcon.setScaleX(0.3f);
        splashIcon.setScaleY(0.3f);
        splashIcon.setAlpha(0f);
        splashContainer.setTranslationY(40f);
        splashContainer.setAlpha(0f);

        splashIcon.animate()
                .scaleX(1.0f)
                .scaleY(1.0f)
                .alpha(1.0f)
                .setDuration(600)
                .setInterpolator(new OvershootInterpolator(1.5f))
                .start();

        splashContainer.animate()
                .translationY(0f)
                .alpha(1.0f)
                .setDuration(700)
                .start();

        // Reveal frontend after opening animation
        new Handler(Looper.getMainLooper()).postDelayed(new Runnable() {
            @Override
            public void run() {
                splashOverlay.animate()
                        .alpha(0f)
                        .setDuration(450)
                        .withEndAction(new Runnable() {
                            @Override
                            public void run() {
                                splashOverlay.setVisibility(View.GONE);
                                if (!currentServer.isEmpty()) {
                                    loadServer(currentServer);
                                } else {
                                    showSetup();
                                }
                            }
                        })
                        .start();
            }
        }, 1100);
    }

    /**
     * Toggle in-app fullscreen mode:
     * Slides away the top bar for a completely unobstructed PC control viewport.
     */
    private void toggleInAppFullscreen(boolean fullscreen) {
        isFullscreenActive = fullscreen;
        applyStickyImmersiveMode();

        if (fullscreen) {
            topBar.animate()
                    .translationY(-topBar.getHeight())
                    .setDuration(250)
                    .withEndAction(new Runnable() {
                        @Override
                        public void run() {
                            topBar.setVisibility(View.GONE);
                        }
                    })
                    .start();

            btnFloatingRestore.setVisibility(View.VISIBLE);
            btnFloatingRestore.setAlpha(0f);
            btnFloatingRestore.animate().alpha(0.85f).setDuration(300).start();
            Toast.makeText(this, "Fullscreen Active • Tap Menu to restore", Toast.LENGTH_SHORT).show();
        } else {
            topBar.setVisibility(View.VISIBLE);
            topBar.animate().translationY(0f).setDuration(250).start();

            btnFloatingRestore.animate()
                    .alpha(0f)
                    .setDuration(200)
                    .withEndAction(new Runnable() {
                        @Override
                        public void run() {
                            btnFloatingRestore.setVisibility(View.GONE);
                        }
                    })
                    .start();
        }
    }

    /**
     * Subtle pulse animation on the live connection indicator dot.
     */
    private void startStatusPulse() {
        ObjectAnimator pulse = ObjectAnimator.ofFloat(statusDot, "alpha", 0.35f, 1.0f);
        pulse.setDuration(850);
        pulse.setRepeatMode(ValueAnimator.REVERSE);
        pulse.setRepeatCount(ValueAnimator.INFINITE);
        pulse.start();
    }

    /**
     * Tactile micro-scale animation when touching interactive buttons.
     */
    private void attachClickAnimation(View view) {
        if (view == null) return;
        view.setOnTouchListener(new View.OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent event) {
                int action = event.getAction();
                if (action == MotionEvent.ACTION_DOWN) {
                    v.animate().scaleX(0.95f).scaleY(0.95f).setDuration(80).start();
                } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                    v.animate().scaleX(1.0f).scaleY(1.0f).setDuration(80).start();
                }
                return false;
            }
        });
    }

    private void vibrateBrief(long ms) {
        try {
            if (vibrator != null && vibrator.hasVibrator()) {
                vibrator.vibrate(ms);
            }
        } catch (Exception ignored) {}
    }

    private void initWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setSupportZoom(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                if (newProgress < 100) {
                    progressBar.setVisibility(View.VISIBLE);
                    progressBar.setProgress(newProgress);
                } else {
                    progressBar.setVisibility(View.GONE);
                }
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.proceed(); // Allow local self-signed or tunnel certificates
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                autoLoginIfPossible(url);
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                Toast.makeText(MainActivity.this, "Connection error: " + description, Toast.LENGTH_SHORT).show();
            }
        });
    }

    /**
     * Automatic secure session injection into the backend controller dashboard.
     */
    private void autoLoginIfPossible(String url) {
        if (!currentPassword.isEmpty() && (url.contains("/login") || url.endsWith(":8765/") || url.endsWith("/"))) {
            String js = "javascript:(function() {" +
                    "var pw = document.getElementById('pw') || document.querySelector('input[type=\"password\"]');" +
                    "if(pw && !pw.value) {" +
                    "  pw.value = '" + currentPassword.replace("'", "\\'") + "';" +
                    "}" +
                    "if (typeof login === 'function') { login(); }" +
                    "else {" +
                    "  var btn = document.querySelector('button[type=\"submit\"]') || document.querySelector('form button');" +
                    "  if (btn) btn.click();" +
                    "}" +
                    "})()";
            webView.evaluateJavascript(js, null);
        }
    }

    private String getSanitizedUrl(String raw) {
        if (raw == null || raw.trim().isEmpty()) return "";
        String url = raw.trim();
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://" + url;
        }
        if (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        return url;
    }

    private void saveConfiguration() {
        currentServer = getSanitizedUrl(editServerUrl.getText().toString());
        currentPassword = editPassword.getText().toString().trim();

        prefs.edit()
                .putString(KEY_SERVER_URL, currentServer)
                .putString(KEY_PASSWORD, currentPassword)
                .apply();

        // Automatically persist in the multiple device history list
        if (!currentServer.isEmpty()) {
            recordDeviceInHistory(currentServer);
        }
    }

    private void recordDeviceInHistory(String url) {
        try {
            String jsonStr = prefs.getString(KEY_SAVED_DEVICES, "[]");
            JSONArray arr = new JSONArray(jsonStr);
            boolean exists = false;
            for (int i = 0; i < arr.length(); i++) {
                if (arr.getString(i).equalsIgnoreCase(url)) {
                    exists = true;
                    break;
                }
            }
            if (!exists) {
                arr.put(url);
                prefs.edit().putString(KEY_SAVED_DEVICES, arr.toString()).apply();
            }
        } catch (Exception ignored) {}
    }

    /**
     * Shows a multiple device switcher dialog allowing the user to select
     * between known / saved remote PCs or configure a new connection.
     */
    private void showDeviceSelectorDialog() {
        try {
            String jsonStr = prefs.getString(KEY_SAVED_DEVICES, "[]");
            JSONArray arr = new JSONArray(jsonStr);
            final List<String> devicesList = new ArrayList<String>();
            if (!currentServer.isEmpty() && !devicesList.contains(currentServer)) {
                devicesList.add(currentServer);
            }
            for (int i = 0; i < arr.length(); i++) {
                String d = arr.getString(i);
                if (!devicesList.contains(d)) {
                    devicesList.add(d);
                }
            }

            final String[] items = new String[devicesList.size() + 3];
            for (int i = 0; i < devicesList.size(); i++) {
                String dev = devicesList.get(i);
                items[i] = (dev.equalsIgnoreCase(currentServer) ? "● [Active] " : "○ ") + dev;
            }
            items[devicesList.size()] = "☁️ Sync Cloud Fleet (Neon / Vercel)";
            items[devicesList.size() + 1] = "➕ Add New Device / Host Setup";
            items[devicesList.size() + 2] = "🛡️ Elevate Host Admin via Windows UAC";

            AlertDialog.Builder builder = new AlertDialog.Builder(this);
            builder.setTitle("🖥️ Switch Device / Remote Host");
            builder.setItems(items, new DialogInterface.OnClickListener() {
                @Override
                public void onClick(DialogInterface dialog, int which) {
                    if (which < devicesList.size()) {
                        String selected = devicesList.get(which);
                        currentServer = selected;
                        editServerUrl.setText(selected);
                        prefs.edit().putString(KEY_SERVER_URL, currentServer).apply();
                        vibrateBrief(40);
                        Toast.makeText(MainActivity.this, "Switched to: " + selected, Toast.LENGTH_SHORT).show();
                        loadServer(selected);
                    } else if (which == devicesList.size()) {
                        syncCloudFleetFromNeon();
                    } else if (which == devicesList.size() + 1) {
                        showSetup();
                    } else if (which == devicesList.size() + 2) {
                        requestAdminElevationOnHost();
                    }
                }
            });
            builder.setNegativeButton("Cancel", null);
            builder.show();
        } catch (Exception e) {
            showSetup();
        }
    }

    private void syncCloudFleetFromNeon() {
        Toast.makeText(this, "☁️ Fetching live fleet from Neon Cloud Coordinator...", Toast.LENGTH_SHORT).show();
        new Thread(new Runnable() {
            @Override
            public void run() {
                int addedCount = 0;
                try {
                    URL u = new URL("https://project-x-alpha-lake.vercel.app/api/devices");
                    HttpURLConnection conn = (HttpURLConnection) u.openConnection();
                    conn.setRequestMethod("GET");
                    conn.setConnectTimeout(5000);
                    conn.setReadTimeout(5000);
                    if (conn.getResponseCode() == 200) {
                        java.io.BufferedReader reader = new java.io.BufferedReader(new java.io.InputStreamReader(conn.getInputStream()));
                        StringBuilder sb = new StringBuilder();
                        String line;
                        while ((line = reader.readLine()) != null) {
                            sb.append(line);
                        }
                        reader.close();

                        JSONObject resp = new JSONObject(sb.toString());
                        JSONArray devices = resp.optJSONArray("devices");
                        if (devices != null) {
                            for (int i = 0; i < devices.length(); i++) {
                                JSONObject dev = devices.getJSONObject(i);
                                String target = dev.optString("tunnel_url", dev.optString("host_url", "")).trim();
                                if (!target.isEmpty()) {
                                    recordDeviceInHistory(target);
                                    addedCount++;
                                }
                            }
                        }
                    }
                    conn.disconnect();
                } catch (Exception ignored) {}

                final int finalAdded = addedCount;
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        Toast.makeText(MainActivity.this, "☁️ Cloud Sync: Updated " + finalAdded + " machine(s)", Toast.LENGTH_SHORT).show();
                        showDeviceSelectorDialog();
                    }
                });
            }
        }).start();
    }

    private void requestAdminElevationOnHost() {
        if (currentServer.isEmpty()) {
            Toast.makeText(this, "Connect to PC backend first", Toast.LENGTH_SHORT).show();
            return;
        }
        vibrateBrief(40);
        Toast.makeText(this, "Requesting Windows UAC Elevation on Host PC...", Toast.LENGTH_SHORT).show();
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    URL u = new URL(currentServer + "/api/system/elevate");
                    HttpURLConnection conn = (HttpURLConnection) u.openConnection();
                    conn.setRequestMethod("POST");
                    conn.setConnectTimeout(3000);
                    conn.setReadTimeout(3000);
                    final int code = conn.getResponseCode();
                    new Handler(Looper.getMainLooper()).post(new Runnable() {
                        @Override
                        public void run() {
                            if (code >= 200 && code < 300) {
                                Toast.makeText(MainActivity.this, "Elevation triggered! Backend restarting with Admin rights.", Toast.LENGTH_LONG).show();
                            } else {
                                Toast.makeText(MainActivity.this, "Elevation response: HTTP " + code, Toast.LENGTH_SHORT).show();
                            }
                        }
                    });
                } catch (final Exception e) {
                    new Handler(Looper.getMainLooper()).post(new Runnable() {
                        @Override
                        public void run() {
                            Toast.makeText(MainActivity.this, "Elevation signal dispatched.", Toast.LENGTH_SHORT).show();
                        }
                    });
                }
            }
        }).start();
    }

    private void connectToServer() {
        saveConfiguration();

        if (currentServer.isEmpty()) {
            Toast.makeText(this, "Please enter your PC Backend URL", Toast.LENGTH_SHORT).show();
            return;
        }

        vibrateBrief(40);
        loadServer(currentServer);
    }

    /**
     * Smooth cross-fade into WebView controller viewport.
     */
    private void loadServer(final String url) {
        applyStickyImmersiveMode();

        setupView.animate()
                .alpha(0f)
                .setDuration(220)
                .withEndAction(new Runnable() {
                    @Override
                    public void run() {
                        setupView.setVisibility(View.GONE);
                        webView.setAlpha(0f);
                        webView.setVisibility(View.VISIBLE);
                        webView.animate().alpha(1.0f).setDuration(250).start();

                        if (statusDot != null) statusDot.setVisibility(View.VISIBLE);
                        String displayUrl = url.replace("http://", "").replace("https://", "");
                        txtAppTitle.setText(displayUrl);
                        webView.loadUrl(url);
                    }
                })
                .start();
    }

    /**
     * Smooth cross-fade to reveal the Frontend Setup & Connection Manager.
     */
    private void showSetup() {
        applyStickyImmersiveMode();
        if (isFullscreenActive) {
            toggleInAppFullscreen(false);
        }

        webView.animate()
                .alpha(0f)
                .setDuration(200)
                .withEndAction(new Runnable() {
                    @Override
                    public void run() {
                        webView.setVisibility(View.GONE);
                        setupView.setAlpha(0f);
                        setupView.setVisibility(View.VISIBLE);
                        setupView.animate().alpha(1.0f).setDuration(250).start();

                        // Gentle entrance animation for the card
                        if (mainCard != null) {
                            mainCard.setTranslationY(30f);
                            mainCard.animate().translationY(0f).setDuration(300).start();
                        }

                        if (statusDot != null) statusDot.setVisibility(View.GONE);
                        txtAppTitle.setText("Project-X Frontend");
                    }
                })
                .start();
    }

    /**
     * Test & Ping Backend PC Server:
     * Probes /api/stats, measures latency in ms, updates UI status and provides haptic feedback.
     */
    private void testBackendPing(final String targetUrl) {
        txtBackendStatus.setText("⚡ Pinging backend " + targetUrl + "...");
        txtBackendStatus.setTextColor(Color.parseColor("#94a3b8"));

        new Thread(new Runnable() {
            @Override
            public void run() {
                final long startTime = System.currentTimeMillis();
                boolean success = false;
                String errorMsg = "";
                long latency = 0;

                try {
                    URL u = new URL(targetUrl + "/api/stats");
                    HttpURLConnection conn = (HttpURLConnection) u.openConnection();
                    conn.setRequestMethod("GET");
                    conn.setConnectTimeout(2500);
                    conn.setReadTimeout(2500);

                    int code = conn.getResponseCode();
                    latency = System.currentTimeMillis() - startTime;
                    if (code >= 200 && code < 405) {
                        success = true;
                    } else {
                        errorMsg = "HTTP " + code;
                    }
                    conn.disconnect();
                } catch (Exception e) {
                    errorMsg = e.getClass().getSimpleName();
                }

                final boolean finalSuccess = success;
                final long finalLatency = latency;
                final String finalError = errorMsg;

                new Handler(Looper.getMainLooper()).post(new Runnable() {
                    @Override
                    public void run() {
                        if (finalSuccess) {
                            txtBackendStatus.setText("● Connected to Backend (" + finalLatency + "ms ping)");
                            txtBackendStatus.setTextColor(Color.parseColor("#10b981"));
                            vibrateBrief(50);
                            Toast.makeText(MainActivity.this, "PC Backend Online! (" + finalLatency + "ms)", Toast.LENGTH_SHORT).show();
                        } else {
                            txtBackendStatus.setText("● Backend Offline (" + finalError + ")");
                            txtBackendStatus.setTextColor(Color.parseColor("#ef4444"));
                            Toast.makeText(MainActivity.this, "Ping failed: " + finalError, Toast.LENGTH_SHORT).show();
                        }
                    }
                });
            }
        }).start();
    }

    /**
     * Emergency One-Tap PC Lock.
     */
    private void quickLockPC() {
        if (currentServer.isEmpty()) {
            Toast.makeText(this, "Connect to a PC backend first", Toast.LENGTH_SHORT).show();
            return;
        }
        vibrateBrief(50);
        Toast.makeText(this, "Sending Lock command to PC...", Toast.LENGTH_SHORT).show();

        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    URL u = new URL(currentServer + "/api/power/lock");
                    HttpURLConnection conn = (HttpURLConnection) u.openConnection();
                    conn.setRequestMethod("POST");
                    conn.setRequestProperty("Content-Type", "application/json");
                    conn.setDoOutput(true);
                    conn.setConnectTimeout(3000);
                    conn.setReadTimeout(3000);

                    OutputStream os = conn.getOutputStream();
                    os.write("{}".getBytes());
                    os.flush();
                    os.close();

                    final int code = conn.getResponseCode();
                    new Handler(Looper.getMainLooper()).post(new Runnable() {
                        @Override
                        public void run() {
                            if (code >= 200 && code < 300) {
                                vibrateBrief(100);
                                Toast.makeText(MainActivity.this, "PC Locked Successfully!", Toast.LENGTH_SHORT).show();
                            } else {
                                Toast.makeText(MainActivity.this, "Lock failed (HTTP " + code + ")", Toast.LENGTH_SHORT).show();
                            }
                        }
                    });
                } catch (final Exception e) {
                    new Handler(Looper.getMainLooper()).post(new Runnable() {
                        @Override
                        public void run() {
                            Toast.makeText(MainActivity.this, "Lock error: " + e.getMessage(), Toast.LENGTH_SHORT).show();
                        }
                    });
                }
            }
        }).start();
    }

    @Override
    public void onBackPressed() {
        if (isFullscreenActive) {
            toggleInAppFullscreen(false);
            return;
        }

        if (webView.getVisibility() == View.VISIBLE && webView.canGoBack()) {
            webView.goBack();
        } else {
            long now = System.currentTimeMillis();
            if (now - lastBackPressTime < 2000) {
                super.onBackPressed();
            } else {
                lastBackPressTime = now;
                Toast.makeText(this, "Press back again to exit", Toast.LENGTH_SHORT).show();
            }
        }
    }
}
