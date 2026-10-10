package io.github.farhanaiml.edusignal;

import android.app.DownloadManager;
import android.content.ContentValues;
import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.WebView;
import android.widget.Toast;

import com.getcapacitor.BridgeActivity;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

/**
 * The app shows the deployed EduSignal web app. Android's WebView ignores file downloads by
 * default, so report exports (PDF/Excel) and table CSV downloads are handled here and saved
 * to the phone's Downloads folder.
 */
public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WebView webView = getBridge().getWebView();
        webView.addJavascriptInterface(new BlobSaver(this), "EduSignalAndroid");
        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, length) -> {
            String name = URLUtil.guessFileName(url, contentDisposition, mimeType);
            if (url.startsWith("blob:")) {
                webView.evaluateJavascript(blobScript(url, name, mimeType), null);
            } else if (url.startsWith("data:")) {
                int comma = url.indexOf(',');
                boolean base64 = url.substring(0, comma).endsWith(";base64");
                String payload = url.substring(comma + 1);
                byte[] bytes = base64 ? Base64.decode(payload, Base64.DEFAULT) : Uri.decode(payload).getBytes();
                saveBytes(this, bytes, name, mimeType);
            } else {
                download(url, userAgent, name, mimeType);
            }
        });
    }

    private void download(String url, String userAgent, String name, String mimeType) {
        try {
            DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
            String cookies = CookieManager.getInstance().getCookie(url);
            if (cookies != null) req.addRequestHeader("Cookie", cookies);
            req.addRequestHeader("User-Agent", userAgent);
            req.setMimeType(mimeType);
            req.setTitle(name);
            req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
            } else {
                req.setDestinationInExternalFilesDir(this, Environment.DIRECTORY_DOWNLOADS, name);
            }
            ((DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE)).enqueue(req);
            Toast.makeText(this, "Downloading " + name, Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            Toast.makeText(this, "Download failed: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    /** Reads a blob: URL inside the page and hands it back as base64 to {@link BlobSaver}. */
    private static String blobScript(String url, String name, String mimeType) {
        return "(function(){fetch(" + quote(url) + ").then(function(r){return r.blob();}).then(function(b){"
                + "var f=new FileReader();f.onloadend=function(){EduSignalAndroid.save(f.result.split(',')[1]||'',"
                + quote(name) + "," + quote(mimeType == null ? "" : mimeType) + ");};f.readAsDataURL(b);})"
                + ".catch(function(e){EduSignalAndroid.failed(String(e));});})();";
    }

    private static String quote(String s) {
        return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'";
    }

    static void saveBytes(Context ctx, byte[] bytes, String name, String mimeType) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentValues values = new ContentValues();
                values.put(MediaStore.Downloads.DISPLAY_NAME, name);
                if (mimeType != null && !mimeType.isEmpty()) values.put(MediaStore.Downloads.MIME_TYPE, mimeType);
                Uri uri = ctx.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                if (uri == null) throw new IllegalStateException("Downloads folder unavailable");
                try (OutputStream out = ctx.getContentResolver().openOutputStream(uri)) {
                    out.write(bytes);
                }
            } else {
                File dir = ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
                try (OutputStream out = new FileOutputStream(new File(dir, name))) {
                    out.write(bytes);
                }
            }
            Toast.makeText(ctx, "Saved " + name + " to Downloads", Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            Toast.makeText(ctx, "Download failed: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    static class BlobSaver {
        private final MainActivity activity;

        BlobSaver(MainActivity activity) {
            this.activity = activity;
        }

        @JavascriptInterface
        public void save(String base64, String name, String mimeType) {
            byte[] bytes = Base64.decode(base64, Base64.DEFAULT);
            activity.runOnUiThread(() -> saveBytes(activity, bytes, name, mimeType));
        }

        @JavascriptInterface
        public void failed(String message) {
            activity.runOnUiThread(() ->
                    Toast.makeText(activity, "Download failed: " + message, Toast.LENGTH_LONG).show());
        }
    }
}
