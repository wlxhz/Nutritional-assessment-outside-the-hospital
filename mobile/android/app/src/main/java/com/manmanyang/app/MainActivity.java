package com.manmanyang.app;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.net.http.SslError;
import android.os.Bundle;
import android.speech.tts.TextToSpeech;
import android.telephony.SmsManager;
import android.webkit.JavascriptInterface;
import android.webkit.SslErrorHandler;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.util.Locale;

public class MainActivity extends Activity {
    private WebView webView;
    private TextToSpeech textToSpeech;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestPermissions(new String[] {
                Manifest.permission.CAMERA,
                Manifest.permission.RECORD_AUDIO,
                Manifest.permission.CALL_PHONE,
                Manifest.permission.SEND_SMS
        }, 1001);

        webView = new WebView(this);
        setContentView(webView);
        textToSpeech = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                textToSpeech.setLanguage(Locale.CHINESE);
            }
        });

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        webView.addJavascriptInterface(new NativeBridge(), "ManmanyangNative");

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.proceed();
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                request.grant(request.getResources());
            }

            @Override
            public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                callback.invoke(origin, true, false);
            }
        });

        webView.loadUrl(getString(R.string.app_url));
    }

    public class NativeBridge {
        @JavascriptInterface
        public void speakRiskAlert(String text) {
            runOnUiThread(() -> {
                if (textToSpeech != null) {
                    textToSpeech.speak(text, TextToSpeech.QUEUE_FLUSH, null, "risk-alert");
                }
            });
        }

        @JavascriptInterface
        public void sendRiskSms(String phone, String message) {
            runOnUiThread(() -> {
                boolean sent = false;
                String error = "";
                try {
                    if (checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
                        requestPermissions(new String[] { Manifest.permission.SEND_SMS }, 1002);
                        error = "SEND_SMS permission not granted";
                    } else {
                        SmsManager smsManager = SmsManager.getDefault();
                        for (String part : smsManager.divideMessage(message)) {
                            smsManager.sendTextMessage(phone, null, part, null, null);
                        }
                        sent = true;
                    }
                } catch (Exception exception) {
                    error = exception.getMessage() == null ? "send sms failed" : exception.getMessage();
                }
                final boolean finalSent = sent;
                final String finalError = error.replace("\\", "\\\\").replace("'", "\\'");
                webView.evaluateJavascript(
                        "window.dispatchEvent(new CustomEvent('mmy-native-sms-result', { detail: { ok: "
                                + finalSent + ", error: '" + finalError + "' } }))",
                        null
                );
            });
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (textToSpeech != null) {
            textToSpeech.stop();
            textToSpeech.shutdown();
        }
        super.onDestroy();
    }
}
