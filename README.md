# EduSignal Mobile (Android + iOS)

A native app shell built with [Capacitor 8](https://capacitorjs.com) around the deployed EduSignal web app
at **https://edusignal.streamlit.app/**. Login, dashboards, the database and AI predictions all run on that
server, exactly as in the browser. This project contains no Python code and does not change the web app.

| Folder / file | Purpose |
|---|---|
| `app.config.json` | **The only place the app URL, app id and name are set.** |
| `scripts/configure.mjs` | Checks the URL is valid and reachable, then writes `capacitor.config.json` and puts the URL into the local pages in `www/`. Stops the build if the URL is empty or broken. |
| `www/` | Local pages: `error.html` (shown when the phone is offline, with a Retry button) and a fallback launcher. |
| `android/` | Android Studio / Gradle project. `MainActivity.java` adds file downloads (PDF/Excel reports, CSV), which Android's WebView ignores by default. |
| `ios/` | Xcode project (Swift Package Manager, no CocoaPods needed). Build it on a Mac. |
| `scripts/make_icons.py` | Draws the EduSignal logo into all Android/iOS icon and splash files (needs Pillow). |

## Requirements

- Node.js 20+ and npm
- **Android:** JDK 21 and the Android SDK (platform 36, build-tools 35). Android Studio is optional.
- **iOS:** a Mac with Xcode 16+ and an Apple ID (a paid Apple Developer account is needed for the App Store or TestFlight).

## Android

```bash
npm install
npm run build:android          # configure + cap sync android + gradlew assembleDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk
```

Install on a phone: copy the APK to the phone and open it (allow "Install unknown apps"),
or with USB debugging on: `adb install -r android/app/build/outputs/apk/debug/app-debug.apk`.

### Release build (Play Store)

Signing keys and passwords are never stored in this project (`*.jks`, `*.keystore` and
`keystore.properties` are git-ignored). Create a key once and keep it safe; losing it means you can't update the app:

```bash
keytool -genkeypair -v -keystore edusignal-release.jks -alias edusignal -keyalg RSA -keysize 2048 -validity 10000
```

Then build a signed bundle from Android Studio (**Build → Generate Signed App Bundle**), or pass the
key through environment variables in your CI. Upload the `.aab` to Google Play Console.

## iOS (on a Mac only)

```bash
npm install
npm run sync                   # configure + cap sync (android and ios)
npx cap open ios               # opens ios/App/App.xcodeproj in Xcode
```

In Xcode: select the **App** target → *Signing & Capabilities* → choose your Team, then run on a device or
*Product → Archive* to upload to App Store Connect / TestFlight.

Without a Mac, iPhone users can still use the web app as an app: open the link in Safari →
Share → **Add to Home Screen**.

## Changing the server URL

Edit `appUrl` in `app.config.json`, then rebuild (`npm run build:android`, or `npm run sync` and rebuild in Xcode).

## Notes

- The app needs internet; all data lives on the server.
- Streamlit Community Cloud puts apps to sleep after a period of inactivity. The first open may show
  Streamlit's wake-up page, and the button there works inside the app.
- The Cloud database is reset when the Streamlit app restarts or is redeployed, so treat it as a demo
  until the web app is moved to persistent hosting.
