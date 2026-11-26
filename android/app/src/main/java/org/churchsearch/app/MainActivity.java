package org.churchsearch.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.nio.charset.StandardCharsets;
import java.util.Enumeration;

public class MainActivity extends Activity {
    private static final String PREFS = "church_search_prefs";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String KEY_LAN_URL = "lan_url";
    private static final String OFFLINE_ENTRY_URL = "file:///android_asset/offline/index.html";
    private static final int DISCOVERY_PORT = 48765;
    private static final int FILE_CHOOSER_REQ = 1001;

    private WebView webView;
    private ScrollView setupScroll;
    private EditText urlInput;
    private TextView statusLabel;
    private Button discoverBtn;
    private ValueCallback<Uri[]> filePathCallback;
    private boolean triedLanFallback = false;
    private boolean inOfflineMode = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#F5F5F7"));

        webView = new WebView(this);
        webView.setLayoutParams(new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        configureWebView();
        root.addView(webView);

        setupScroll = buildSetupView();
        root.addView(setupScroll);

        setContentView(root);

        if (handleDeepLinkIntent(getIntent())) {
            return;
        }

        String savedUrl = getPrefs().getString(KEY_SERVER_URL, "").trim();
        if (savedUrl.isEmpty()) {
            showSetupView("QR 자동 연결, 같은 Wi-Fi PC 자동 찾기, 또는 인터넷 없는 오프라인 모드를 선택하세요.");
        } else {
            loadServer(savedUrl, false);
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleDeepLinkIntent(intent);
    }

    private boolean handleDeepLinkIntent(Intent intent) {
        if (intent == null) return false;
        Uri data = intent.getData();
        if (data == null) return false;
        if ("churchsearch".equalsIgnoreCase(data.getScheme()) && "connect".equalsIgnoreCase(data.getHost())) {
            String ext = normalizeUrl(data.getQueryParameter("url"));
            String lan = normalizeUrl(data.getQueryParameter("lan"));
            String primary = !ext.isEmpty() ? ext : lan;
            if (!primary.isEmpty()) {
                SharedPreferences.Editor ed = getPrefs().edit();
                ed.putString(KEY_SERVER_URL, primary);
                if (!lan.isEmpty()) {
                    ed.putString(KEY_LAN_URL, lan);
                }
                ed.apply();
                Toast.makeText(this, "QR 연결 주소가 자동 저장되었습니다.", Toast.LENGTH_SHORT).show();
                loadServer(primary, false);
                return true;
            }
        }
        return false;
    }

    private SharedPreferences getPrefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private GradientDrawable roundedBg(String hexFill, String hexStroke, int radiusDp) {
        GradientDrawable gd = new GradientDrawable();
        gd.setColor(Color.parseColor(hexFill));
        gd.setCornerRadius(dp(radiusDp));
        if (hexStroke != null) {
            gd.setStroke(dp(1), Color.parseColor(hexStroke));
        }
        return gd;
    }

    private ScrollView buildSetupView() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Color.parseColor("#F5F5F7"));
        scroll.setLayoutParams(new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout outer = new LinearLayout(this);
        outer.setOrientation(LinearLayout.VERTICAL);
        outer.setGravity(Gravity.CENTER);
        int pad = dp(20);
        outer.setPadding(pad, dp(36), pad, dp(36));

        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(roundedBg("#FFFFFF", "#E2E8F0", 20));
        card.setPadding(dp(22), dp(26), dp(22), dp(24));
        LinearLayout.LayoutParams cardLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        outer.addView(card, cardLp);

        TextView title = new TextView(this);
        title.setText("목포사랑의교회 행정Q&A");
        title.setTextSize(20f);
        title.setTextColor(Color.parseColor("#1D1D1F"));
        title.setGravity(Gravity.CENTER);
        card.addView(title);

        statusLabel = new TextView(this);
        statusLabel.setText("연결 방식을 선택하세요.");
        statusLabel.setTextSize(13f);
        statusLabel.setTextColor(Color.parseColor("#6E6E73"));
        statusLabel.setGravity(Gravity.CENTER);
        statusLabel.setPadding(0, dp(8), 0, dp(18));
        card.addView(statusLabel);

        // 1. Offline mode instant button (works 100% in Airplane Mode / PC turned off)
        Button offlineBtn = new Button(this);
        offlineBtn.setText("오프라인 모드로 바로 열기 (인터넷 불필요)");
        offlineBtn.setAllCaps(false);
        offlineBtn.setTextColor(Color.parseColor("#007AFF"));
        offlineBtn.setBackground(roundedBg("#EFF6FF", "#BFDBFE", 12));
        offlineBtn.setOnClickListener(v -> openOfflineMode());
        LinearLayout.LayoutParams lpOffline = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(46));
        lpOffline.bottomMargin = dp(10);
        card.addView(offlineBtn, lpOffline);

        // 2. 1-tap Same-Wi-Fi UDP Auto-Discovery
        discoverBtn = new Button(this);
        discoverBtn.setText("같은 Wi-Fi PC 자동 찾기");
        discoverBtn.setAllCaps(false);
        discoverBtn.setTextColor(Color.parseColor("#1D1D1F"));
        discoverBtn.setBackground(roundedBg("#F5F5F7", "#D1D5DB", 12));
        discoverBtn.setOnClickListener(v -> discoverPcOnLan());
        LinearLayout.LayoutParams lpDisc = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(46));
        lpDisc.bottomMargin = dp(18);
        card.addView(discoverBtn, lpDisc);

        TextView inputHint = new TextView(this);
        inputHint.setText("Tailscale HTTPS 또는 Wi-Fi 서버 주소 (QR 스캔 시 자동 입력)");
        inputHint.setTextSize(11.5f);
        inputHint.setTextColor(Color.parseColor("#6E6E73"));
        inputHint.setPadding(dp(2), 0, 0, dp(6));
        card.addView(inputHint);

        urlInput = new EditText(this);
        urlInput.setHint("예: https://...ts.net 또는 http://192.168.0.10:8765");
        urlInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        urlInput.setSingleLine(true);
        urlInput.setTextSize(14f);
        urlInput.setTextColor(Color.parseColor("#1D1D1F"));
        urlInput.setBackground(roundedBg("#F8FAFC", "#CBD5E1", 10));
        urlInput.setPadding(dp(12), dp(12), dp(12), dp(12));
        urlInput.setText(getPrefs().getString(KEY_SERVER_URL, ""));
        LinearLayout.LayoutParams lpInput = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lpInput.bottomMargin = dp(12);
        card.addView(urlInput, lpInput);

        Button connectBtn = new Button(this);
        connectBtn.setText("온라인 서버 연결하기");
        connectBtn.setAllCaps(false);
        connectBtn.setTextColor(Color.WHITE);
        connectBtn.setBackground(roundedBg("#18181B", null, 12));
        connectBtn.setOnClickListener(v -> {
            String raw = normalizeUrl(urlInput.getText().toString());
            if (raw.isEmpty()) {
                Toast.makeText(this, "올바른 서버 주소를 입력해 주세요.", Toast.LENGTH_SHORT).show();
                return;
            }
            getPrefs().edit().putString(KEY_SERVER_URL, raw).apply();
            loadServer(raw, false);
        });
        card.addView(connectBtn, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(46)));

        scroll.addView(outer);
        return scroll;
    }

    private void discoverPcOnLan() {
        discoverBtn.setEnabled(false);
        discoverBtn.setText("같은 Wi-Fi에서 교회 PC 검색 중...");
        statusLabel.setText("같은 네트워크의 교회검색기 PC를 찾고 있습니다...");

        new Thread(() -> {
            String foundExternal = "";
            String foundLan = "";
            String foundName = "";
            DatagramSocket sock = null;
            try {
                sock = new DatagramSocket();
                sock.setBroadcast(true);
                sock.setSoTimeout(2200);

                byte[] probe = "CHURCH_SEARCH_DISCOVER".getBytes(StandardCharsets.UTF_8);
                // Broadcast on global broadcast + all IPv4 interface broadcasts
                try {
                    sock.send(new DatagramPacket(probe, probe.length, InetAddress.getByName("255.255.255.255"), DISCOVERY_PORT));
                } catch (Exception ignored) {}

                Enumeration<NetworkInterface> ifaces = NetworkInterface.getNetworkInterfaces();
                while (ifaces != null && ifaces.hasMoreElements()) {
                    NetworkInterface ni = ifaces.nextElement();
                    if (!ni.isUp() || ni.isLoopback()) continue;
                    for (InterfaceAddress ia : ni.getInterfaceAddresses()) {
                        InetAddress bcast = ia.getBroadcast();
                        if (bcast != null) {
                            try {
                                sock.send(new DatagramPacket(probe, probe.length, bcast, DISCOVERY_PORT));
                            } catch (Exception ignored) {}
                        }
                    }
                }

                byte[] buf = new byte[2048];
                DatagramPacket reply = new DatagramPacket(buf, buf.length);
                sock.receive(reply);
                String jsonStr = new String(reply.getData(), 0, reply.getLength(), StandardCharsets.UTF_8);
                JSONObject obj = new JSONObject(jsonStr);
                if ("church-search".equals(obj.optString("app"))) {
                    foundLan = normalizeUrl(obj.optString("lan_url", ""));
                    foundExternal = normalizeUrl(obj.optString("external_url", ""));
                    foundName = obj.optString("name", "교회검색기 PC");
                }
            } catch (Exception ignored) {
            } finally {
                if (sock != null) sock.close();
            }

            final String fExt = foundExternal;
            final String fLan = foundLan;
            final String fName = foundName;
            runOnUiThread(() -> {
                discoverBtn.setEnabled(true);
                discoverBtn.setText("같은 Wi-Fi PC 자동 찾기");
                String target = !fLan.isEmpty() ? fLan : fExt;
                if (!target.isEmpty()) {
                    SharedPreferences.Editor ed = getPrefs().edit();
                    ed.putString(KEY_SERVER_URL, !fExt.isEmpty() ? fExt : fLan);
                    if (!fLan.isEmpty()) ed.putString(KEY_LAN_URL, fLan);
                    ed.apply();
                    urlInput.setText(!fExt.isEmpty() ? fExt : fLan);
                    Toast.makeText(MainActivity.this, fName + " 연결됨!", Toast.LENGTH_SHORT).show();
                    loadServer(target, false);
                } else {
                    statusLabel.setText("같은 Wi-Fi에서 실행 중인 PC를 찾지 못했습니다. PC 앱의 [연결·QR]을 스캔하거나 오프라인 모드를 사용하세요.");
                }
            });
        }).start();
    }

    private String normalizeUrl(String input) {
        String s = input == null ? "" : input.trim();
        if (s.isEmpty()) return "";
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            s = "http://" + s;
        }
        return s.replaceAll("/+$", "");
    }

    private void showSetupView(String message) {
        inOfflineMode = false;
        statusLabel.setText(message);
        urlInput.setText(getPrefs().getString(KEY_SERVER_URL, ""));
        setupScroll.setVisibility(View.VISIBLE);
        webView.setVisibility(View.GONE);
    }

    private void openOfflineMode() {
        inOfflineMode = true;
        setupScroll.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        webView.loadUrl(OFFLINE_ENTRY_URL);
    }

    private void loadServer(String url, boolean isFallbackAttempt) {
        inOfflineMode = false;
        if (!isFallbackAttempt) {
            triedLanFallback = false;
        }
        setupScroll.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        webView.loadUrl(url);
    }

    private void configureWebView() {
        WebSettings ws = webView.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setDatabaseEnabled(true);
        ws.setAllowFileAccess(true);
        ws.setLoadWithOverviewMode(true);
        ws.setUseWideViewPort(true);
        ws.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);

        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(webView, true);

        webView.addJavascriptInterface(new Bridge(), "AndroidApp");

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame() && !inOfflineMode) {
                    String lan = getPrefs().getString(KEY_LAN_URL, "").trim();
                    String cur = request.getUrl() != null ? request.getUrl().toString() : "";
                    if (!triedLanFallback && !lan.isEmpty() && !cur.startsWith(lan)) {
                        triedLanFallback = true;
                        loadServer(lan, true);
                        return;
                    }
                    showSetupView("PC 서버에 연결할 수 없습니다. 인터넷이 없거나 PC가 꺼져 있다면 [오프라인 모드로 바로 열기]를 이용하세요.");
                }
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(
                    WebView webView,
                    ValueCallback<Uri[]> callback,
                    FileChooserParams params) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = callback;
                Intent intent = params.createIntent();
                try {
                    startActivityForResult(intent, FILE_CHOOSER_REQ);
                } catch (Exception e) {
                    filePathCallback = null;
                    return false;
                }
                return true;
            }
        });

        webView.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition, String mimeType, long contentLength) {
                try {
                    DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
                    req.setMimeType(mimeType);
                    String cookies = CookieManager.getInstance().getCookie(url);
                    if (cookies != null) {
                        req.addRequestHeader("Cookie", cookies);
                    }
                    req.addRequestHeader("User-Agent", userAgent);
                    String filename = URLUtil.guessFileName(url, contentDisposition, mimeType);
                    req.setTitle(filename);
                    req.setDescription("교회검색기 파일 다운로드 중...");
                    req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                    req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename);
                    DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
                    if (dm != null) {
                        dm.enqueue(req);
                        Toast.makeText(MainActivity.this, "다운로드를 시작했습니다: " + filename, Toast.LENGTH_LONG).show();
                    }
                } catch (Exception e) {
                    Intent browserIntent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                    startActivity(browserIntent);
                }
            }
        });
    }

    private void exportAndOpenAssetPdf(String assetPath, String filename) {
        String safeName = (filename == null || filename.trim().isEmpty()) ? "form.pdf" : filename.replaceAll("[\\\\/:*?\"<>|]+", "_");
        if (!safeName.toLowerCase().endsWith(".pdf")) {
            safeName = safeName + ".pdf";
        }
        try (InputStream in = getAssets().open(assetPath)) {
            Uri openUri = null;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentValues cv = new ContentValues();
                cv.put(MediaStore.Downloads.DISPLAY_NAME, safeName);
                cv.put(MediaStore.Downloads.MIME_TYPE, "application/pdf");
                cv.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/목포사랑의교회 행정Q&A");
                Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
                if (uri != null) {
                    try (OutputStream out = getContentResolver().openOutputStream(uri)) {
                        if (out != null) {
                            byte[] buf = new byte[8192];
                            int len;
                            while ((len = in.read(buf)) != -1) {
                                out.write(buf, 0, len);
                            }
                        }
                    }
                    openUri = uri;
                }
            } else {
                File dir = getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS);
                if (dir != null) {
                    if (!dir.exists()) dir.mkdirs();
                    File outFile = new File(dir, safeName);
                    try (OutputStream out = new FileOutputStream(outFile)) {
                        byte[] buf = new byte[8192];
                        int len;
                        while ((len = in.read(buf)) != -1) {
                            out.write(buf, 0, len);
                        }
                    }
                    openUri = Uri.fromFile(outFile);
                }
            }

            if (openUri != null) {
                Toast.makeText(this, "다운로드/교회검색기 폴더에 저장됨: " + safeName, Toast.LENGTH_LONG).show();
                Intent viewIntent = new Intent(Intent.ACTION_VIEW);
                viewIntent.setDataAndType(openUri, "application/pdf");
                viewIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                try {
                    startActivity(Intent.createChooser(viewIntent, "PDF 열기"));
                } catch (Exception ignored) {}
            } else {
                Toast.makeText(this, "PDF 저장에 실패했습니다.", Toast.LENGTH_SHORT).show();
            }
        } catch (Exception e) {
            Toast.makeText(this, "내장 PDF를 열 수 없습니다: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_CHOOSER_REQ && filePathCallback != null) {
            Uri[] result = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
            filePathCallback.onReceiveValue(result);
            filePathCallback = null;
        }
    }

    @Override
    public void onBackPressed() {
        if (setupScroll.getVisibility() == View.VISIBLE) {
            super.onBackPressed();
            return;
        }
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            new AlertDialog.Builder(this)
                    .setTitle("목포사랑의교회 행정Q&A")
                    .setMessage("앱을 종료하거나 연결 방식을 변경할 수 있습니다.")
                    .setPositiveButton("종료", (d, w) -> finish())
                    .setNeutralButton("연결·오프라인 전환", (d, w) -> showSetupView("온라인 서버 연결 또는 오프라인 모드를 선택하세요."))
                    .setNegativeButton("취소", null)
                    .show();
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private class Bridge {
        @JavascriptInterface
        public void openServerSettings() {
            runOnUiThread(() -> showSetupView("온라인 서버 연결 또는 오프라인 모드를 선택하세요."));
        }

        @JavascriptInterface
        public void openOfflineMode() {
            runOnUiThread(MainActivity.this::openOfflineMode);
        }

        @JavascriptInterface
        public void openOfflineFormPdf(String formId, String filename) {
            String cleanId = formId == null ? "" : formId.replaceAll("[^A-Za-z0-9_\\-]", "");
            runOnUiThread(() -> exportAndOpenAssetPdf("offline/forms/" + cleanId + ".pdf", filename));
        }

        @JavascriptInterface
        public void openOfflineDocPdf(String docId, String filename) {
            String cleanId = docId == null ? "" : docId.replaceAll("[^A-Za-z0-9_\\-]", "");
            runOnUiThread(() -> exportAndOpenAssetPdf("offline/pdfs/" + cleanId + ".pdf", filename));
        }
    }
}
