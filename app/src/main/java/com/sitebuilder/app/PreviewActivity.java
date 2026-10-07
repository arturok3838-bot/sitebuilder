package com.sitebuilder.app;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class PreviewActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        ThemeManager.applyTheme(this);
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_preview);

        WebView webView = findViewById(R.id.webView);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.setWebViewClient(new WebViewClient());

        String html = getIntent().getStringExtra("html");
        if (html == null) html = "<h1>Пусто</h1>";

        webView.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null);
    }
}
