package com.remotepc.controller;

import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
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

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends Activity {

    private static final String PREFS_NAME = "RemotePC_Prefs";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String KEY_PASSWORD = "password";

    private WebView webView;
    private View setupView;
    private ProgressBar progressBar;
    private EditText editServerUrl;
    private EditText editPassword;
    private TextView txtAppTitle;
    private SharedPreferences prefs;

    private String currentServer = "";
    private String currentPassword = "";
    private long lastBackPressTime = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);

        webView = findViewById(R.id.webView);
        setupView = findViewById(R.id.setupView);
        progressBar = findViewById(R.id.progressBar);
        editServerUrl = findViewById(R.id.editServerUrl);
        editPassword = findViewById(R.id.editPassword);
        txtAppTitle = findViewById(R.id.txtAppTitle);

        Button btnConnect = findViewById(R.id.btnConnect);
        Button btnQuickLock = findViewById(R.id.btnQuickLock);
        Button btnSwitchPC = findViewById(R.id.btnSwitchPC);
        Button btnRefresh = findViewById(R.id.btnRefresh);

        initWebView();

        currentServer = prefs.getString(KEY_SERVER_URL, "");
        currentPassword = prefs.getString(KEY_PASSWORD, "");

        editServerUrl.setText(currentServer);
        editPassword.setText(currentPassword);

        btnConnect.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                connectToServer();
            }
        });

        btnSwitchPC.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showSetup();
            }
        });

        btnRefresh.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (webView.getVisibility() == View.VISIBLE) {
                    webView.reload();
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

        if (!currentServer.isEmpty()) {
            loadServer(currentServer);
        } else {
            showSetup();
        }
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
                handler.proceed(); // Allow local self-signed certificates
            }

            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                super.onPageStarted(view, url, favicon);
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

    private void autoLoginIfPossible(String url) {
        if (!currentPassword.isEmpty() && (url.contains("/login") || url.endsWith(":8765/"))) {
            String js = "javascript:(function() {" +
                    "var pw = document.querySelector('input[type=\"password\"]');" +
                    "var btn = document.querySelector('button[type=\"submit\"]') || document.querySelector('form button');" +
                    "if(pw && !pw.value && btn) {" +
                    "  pw.value = '" + currentPassword.replace("'", "\\'") + "';" +
                    "  btn.click();" +
                    "}" +
                    "})()";
            webView.evaluateJavascript(js, null);
        }
    }

    private void connectToServer() {
        String url = editServerUrl.getText().toString().trim();
        String pw = editPassword.getText().toString().trim();

        if (url.isEmpty()) {
            Toast.makeText(this, "Please enter your Server URL", Toast.LENGTH_SHORT).show();
            return;
        }

        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://" + url;
        }
        if (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }

        currentServer = url;
        currentPassword = pw;

        prefs.edit()
                .putString(KEY_SERVER_URL, currentServer)
                .putString(KEY_PASSWORD, currentPassword)
                .apply();

        loadServer(currentServer);
    }

    private void loadServer(String url) {
        setupView.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        txtAppTitle.setText(url.replace("http://", "").replace("https://", ""));
        webView.loadUrl(url);
    }

    private void showSetup() {
        webView.setVisibility(View.GONE);
        setupView.setVisibility(View.VISIBLE);
        txtAppTitle.setText("RemotePC Setup");
    }

    private void quickLockPC() {
        if (currentServer.isEmpty()) {
            Toast.makeText(this, "Connect to a PC first", Toast.LENGTH_SHORT).show();
            return;
        }
        Toast.makeText(this, "Sending Lock command...", Toast.LENGTH_SHORT).show();

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
                                Toast.makeText(MainActivity.this, "PC Screen Locked!", Toast.LENGTH_SHORT).show();
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
