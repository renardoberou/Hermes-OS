package com.resonantsystems.hermesos;

import android.Manifest;
import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.Toast;

public class MainActivity extends Activity {
    private static final String ASSET_DASHBOARD = "file:///android_asset/index.html";
    private static final String LIVE_PUBLIC_DASHBOARD = "file:///storage/emulated/0/Documents/HermesOS/index.html";
    private static final String LIVE_TERMUX_DASHBOARD = "/data/data/com.termux/files/home/hermes-android-agentic-os/dist/index.html";
    private static final String SHELL_COMMAND = "clear; ~/.local/bin/hermes-os status; echo; echo 'Dashboard mirror:'; echo '/storage/emulated/0/Documents/HermesOS/index.html'";
    private static final String RUN_COMMAND_PERMISSION = "com.termux.permission.RUN_COMMAND";
    private static final String HERMES_OS_PATH = "/data/data/com.termux/files/home/.local/bin/hermes-os";
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestStoragePermissionIfNeeded();
        requestRunCommandPermissionIfNeeded();

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(18, 13, 8));

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setPadding(dp(8), dp(8), dp(8), dp(8));
        bar.setBackgroundColor(Color.rgb(28, 21, 16));

        Button reload = makeButton("Reload");
        Button live = makeButton("Live");
        Button shell = makeButton("Shell");
        bar.addView(reload);
        bar.addView(live);
        bar.addView(shell);

        webView = new WebView(this);
        LinearLayout.LayoutParams webParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0,
                1f
        );
        webView.setLayoutParams(webParams);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(false);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return request != null && handleDashboardUrl(request.getUrl());
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, android.webkit.WebResourceError error) {
                if (request == null || request.isForMainFrame()) {
                    Toast.makeText(MainActivity.this, "Live dashboard unavailable; showing bundled snapshot", Toast.LENGTH_LONG).show();
                    view.loadUrl(ASSET_DASHBOARD);
                }
            }
        });
        loadLiveDashboard();

        root.addView(bar);
        root.addView(webView);
        setContentView(root);

        reload.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { loadLiveDashboard(); }
        });
        live.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                loadLiveDashboard();
                Toast.makeText(MainActivity.this, "Reloaded live dashboard mirror", Toast.LENGTH_SHORT).show();
            }
        });
        shell.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                copyShellCommandToClipboard();
                openTermux();
            }
        });
    }

    private void requestStoragePermissionIfNeeded() {
        if (android.os.Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE}, 7);
        }
    }

    private void requestRunCommandPermissionIfNeeded() {
        if (android.os.Build.VERSION.SDK_INT >= 23 && checkSelfPermission(RUN_COMMAND_PERMISSION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{RUN_COMMAND_PERMISSION}, 8);
        }
    }

    private void loadLiveDashboard() {
        if (webView == null) return;
        webView.clearCache(true);
        webView.loadUrl(LIVE_PUBLIC_DASHBOARD + "?t=" + System.currentTimeMillis());
    }

    private Button makeButton(String text) {
        Button b = new Button(this);
        b.setText(text);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        p.setMargins(dp(3), 0, dp(3), 0);
        b.setLayoutParams(p);
        return b;
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private void copyShellCommandToClipboard() {
        copyTextToClipboard("Hermes OS shell command", SHELL_COMMAND);
        Toast.makeText(this, "Shell command copied. Paste in Termux.", Toast.LENGTH_LONG).show();
    }

    private boolean handleDashboardUrl(Uri uri) {
        if (uri == null || !"hermesos".equals(uri.getScheme())) return false;
        String action = uri.getHost();
        if ("decision".equals(action)) return handleDecisionUrl(uri);
        if ("apply".equals(action)) return handleApplyUrl(uri);
        if ("system".equals(action)) return handleSystemUrl(uri);
        String text = uri.getQueryParameter("text");
        String cmd = uri.getQueryParameter("cmd");
        String payload = cmd != null && cmd.length() > 0 ? cmd : text;
        if (payload == null || payload.length() == 0) {
            Toast.makeText(this, "No command/text attached to this action", Toast.LENGTH_SHORT).show();
            return true;
        }
        if ("copy".equals(action)) {
            copyTextToClipboard("Hermes OS action", payload);
            Toast.makeText(this, "Copied action to clipboard", Toast.LENGTH_SHORT).show();
            return true;
        }
        if ("termux".equals(action)) {
            copyTextToClipboard("Hermes OS Termux command", payload);
            Toast.makeText(this, "Command copied. Paste in Termux; nothing was run.", Toast.LENGTH_LONG).show();
            openTermux();
            return true;
        }
        Toast.makeText(this, "Unknown Hermes OS action: " + action, Toast.LENGTH_SHORT).show();
        return true;
    }

    private boolean handleDecisionUrl(Uri uri) {
        String id = uri.getQueryParameter("id");
        String verb = uri.getQueryParameter("verb");
        if (!isSafeId(id) || !("approve".equals(verb) || "reject".equals(verb) || "done".equals(verb))) {
            Toast.makeText(this, "Refused invalid decision action", Toast.LENGTH_LONG).show();
            return true;
        }
        runStructuredAction(id, verb);
        return true;
    }

    private boolean handleApplyUrl(Uri uri) {
        String id = uri.getQueryParameter("id");
        String mode = uri.getQueryParameter("mode");
        String verb = "execute".equals(mode) ? "execute" : "dry-run".equals(mode) ? "dry-run" : "";
        if (!isSafeId(id) || verb.length() == 0) {
            Toast.makeText(this, "Refused invalid apply action", Toast.LENGTH_LONG).show();
            return true;
        }
        runStructuredAction(id, verb);
        return true;
    }

    private boolean handleSystemUrl(Uri uri) {
        String verb = uri.getQueryParameter("verb");
        if (!"refresh".equals(verb)) {
            Toast.makeText(this, "Refused invalid system action", Toast.LENGTH_LONG).show();
            return true;
        }
        runStructuredAction("system", "refresh");
        return true;
    }

    private boolean isSafeId(String value) {
        return value != null && value.matches("[A-Za-z0-9._-]{1,80}");
    }

    private void runStructuredAction(String id, String verb) {
        String[] args = new String[]{"action", id, "--verb", verb, "--source", "android-shell"};
        if (!hasRunCommandPermission()) {
            String fallback = "hermes-os action " + id + " --verb " + verb + " --source android-shell";
            copyTextToClipboard("Hermes OS structured action", fallback);
            Toast.makeText(this, "Grant Run commands in Termux environment. Action copied as fallback.", Toast.LENGTH_LONG).show();
            openTermux();
            return;
        }
        runTermuxCommand(HERMES_OS_PATH, args, true);
        Toast.makeText(this, "Dispatched " + verb + " for " + id, Toast.LENGTH_SHORT).show();
        if (webView != null) {
            webView.postDelayed(new Runnable() {
                @Override public void run() { loadLiveDashboard(); }
            }, 2200);
        }
    }

    private boolean hasRunCommandPermission() {
        return android.os.Build.VERSION.SDK_INT < 23 || checkSelfPermission(RUN_COMMAND_PERMISSION) == PackageManager.PERMISSION_GRANTED;
    }

    private void copyTextToClipboard(String label, String text) {
        ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (clipboard != null) {
            clipboard.setPrimaryClip(ClipData.newPlainText(label, text));
        }
    }

    private void runTermuxCommand(String path, String[] args, boolean background) {
        if (!hasRunCommandPermission()) {
            Toast.makeText(this, "Missing Termux RUN_COMMAND permission", Toast.LENGTH_LONG).show();
            return;
        }
        Intent intent = new Intent("com.termux.RUN_COMMAND");
        intent.setClassName("com.termux", "com.termux.app.RunCommandService");
        intent.putExtra("com.termux.RUN_COMMAND_PATH", path);
        intent.putExtra("com.termux.RUN_COMMAND_ARGUMENTS", args);
        intent.putExtra("com.termux.RUN_COMMAND_WORKDIR", "/data/data/com.termux/files/home");
        intent.putExtra("com.termux.RUN_COMMAND_BACKGROUND", background);
        intent.putExtra("com.termux.RUN_COMMAND_SESSION_ACTION", "0");
        try {
            startService(intent);
        } catch (SecurityException e) {
            Toast.makeText(this, "Enable Termux allow-external-apps and grant Run commands permission", Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, "Termux RUN_COMMAND service unavailable; opening Termux", Toast.LENGTH_LONG).show();
            openTermux();
        }
    }

    private void openTermux() {
        Intent launch = getPackageManager().getLaunchIntentForPackage("com.termux");
        if (launch != null) {
            startActivity(launch);
            return;
        }
        try {
            Intent settingsIntent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
            settingsIntent.setData(Uri.parse("package:com.termux"));
            startActivity(settingsIntent);
        } catch (Exception e) {
            Toast.makeText(this, "Termux not found", Toast.LENGTH_LONG).show();
        }
    }
}
