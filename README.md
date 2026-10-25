<div align="center">

<img src="assets/SLS_Mass_Notif_App.png" width="144" alt="Southland Servers Mass Notify logo">

# SLS Mass Notify

**Live announcements and weather alerts for Windows desktops.**

The desktop client for [Southland Servers Mass Notify for FreePBX](https://github.com/vipgabe09267/SouthlandServers_Mass_Notify_server).

[**Download the installer · 1.0.13-beta**](https://github.com/vipgabe09267/SouthlandServers_Mass_Notify_app/releases/download/v1.0.13-beta/SLS_Mass_Notify_Installer.exe) · [Release notes](CHANGELOG.md) · [Windows build checks](https://github.com/vipgabe09267/SouthlandServers_Mass_Notify_app/actions/workflows/ci.yml)

</div>

## Get started

Requires **Windows x64** and desktop credentials configured on your PBX. Python is included in the installer.

1. Download **SLS_Mass_Notify_Installer.exe** and run it. Installation requires administrator access.
2. Open **SLS Mass Notify** from the Start Menu.
3. Enter the PBX **HTTPS address**, desktop username, and password in Settings, then save.
4. Select **Test connection** to check authentication and delivery activity. Select **Local preview** to check the window and sound.
5. Send a new desktop announcement from the PBX to confirm delivery to this computer.

The connection test does not send an announcement. Up to three PBX profiles can run together. Use credentials assigned to this desktop; administrator API credentials do not belong in the app.

**Releases contain one uploaded asset: the installer EXE.** GitHub also supplies source ZIP/TAR archives automatically. Those are for developers and are not installation packages.

The current prerelease is **1.0.13-beta**. It restores notification overlays, adds **URGENT** and **Regular** labels, improves Piper speech for announcements and weather alerts, and hardens delivery, receipt handling, and dependency security.

## What the app does

| Feature | Behavior |
| --- | --- |
| Live delivery | Receives announcements while connected. Messages missed during sleep, shutdown, or disconnection are skipped. |
| Automatic recovery | Uses Windows suspend/resume and IPv4/IPv6 address-change notifications to retire stale connections. Gives Windows 90 seconds after startup or wake to restore connectivity without connection-error notices. |
| Delivery transport | Starts with authenticated polling and follows the PBX's transport preference. PHP-FPM stays on healthy polling; available SSE continues the negotiated cursor. A full stream pool switches immediately to polling and retains Retry-After. |
| Visual alerts | Displays colored announcements and image-backed weather alerts in one full-size view. Text remains available in **Details** and as the image loading/failure fallback. |
| Notification speech | Reads announcements and weather alerts aloud with local Piper speech after the notification sound. Enabled by default with Lessac low; seven other voices are optional downloads. |
| Expiry | Announcements disappear within ten minutes of publication, or earlier when specified by the sender. Weather alerts retain their published expiry. |
| Receipts | Sends automatic acknowledgements for the exact published event ID independently of image loading or Dismiss. Honors server retry delays, retains terminal rejections for review, and bounds the retry queue. |
| Incident responses | On a compatible PBX, **Respond to incident** offers explicit read, safe, and assistance responses for the assigned desktop participant. Available from the notification and History. |
| Client version | Reports the packaged app version and supported protocols to the PBX on authenticated requests. |
| PBX identity | Labels notifications and history with the configured PBX name. Separates event IDs, receipts, and incident records by origin, account, and the PBX's reported enrollment ID. |
| Tray controls | Provides Settings, History, Health, and Exit. Settings includes sound selection, local preview, and diagnostic export. |

Routine notifications have a single **Dismiss** button. Persistent alerts use **I have read this alert**; that action is stored locally. Automatic receipts confirm software receipt, not human reading or safety. Dismiss does not close a backend incident.

For incident announcements from PBX **0.1.6-beta or later**, select **Respond to incident** to load your authorized assignment. A response shows as confirmed only after the PBX confirms it. An unconfirmed response stays saved; use **Retry** to resend the same request. Human safety responses are never retried automatically. Closing or dismissing an alert sends no human response. A network change preserves already displayed alerts while retiring waiting messages; sleep retires both.

History retains the original incident notification while its human response is unconfirmed, even beyond normal content retention, so the saved request remains available for a deliberate retry. This stays with the original PBX enrollment. Once confirmed, normal History retention applies.

Windows fit the monitor's usable area, including its taskbar. Notices appear at the bottom right of the primary screen, with Settings and Dismiss controls. Notices disappear when their fault clears. Brief recovery failures do not produce an error sound. An outage that continues for five minutes after the recovery period produces one notice. Authentication and configuration faults remain visible in **Health** during recovery.

Notification popups stay above other application windows for both urgent and regular messages. Their priority is labeled **URGENT** or **Regular**, including colored/image-backed announcements; tests retain a separate **TEST / EXERCISE** marker. Normal announcements keep Dismiss and their original expiry rules.

### Notification speech

In **Settings → Notification sound**, use **Read announcements and alerts aloud (Piper)** to turn speech on or off and choose a voice. **English (US) · lessac · low** is included and selected by default. Amy low, Lessac medium, Ryan low, French Siwis medium, German Thorsten low, Portuguese (Brazil) Faber medium, and Spanish Davefx medium are optional downloads. Select one and click **Download voice**; progress and cancellation are available. Each optional voice is about **60 MiB**. Selecting a voice changes pronunciation; it does not translate announcements.

**Test voice** reads a short sample with the currently selected voice, without a chime, PBX connection, or saved-setting change. Its status shows when speech is being prepared and played. This is separate from **Play sound** (chime only), **Local preview** (notification display and audio), and the PBX connection test. Speech is prepared during the chime, then played when both are ready; dismissing the notification cancels its audio. One hidden Piper worker warms in the background when speech is enabled and keeps the selected voice loaded between notifications, avoiding a fresh interpreter and model load for every message. Speech diagnostics record stages, voice names, and timings without recording notification text.

Installed voices work offline and send no notification text to a speech service. Downloading a voice requires an internet connection, uses pinned HTTPS sources, and sends no PBX credentials or announcement text. Downloads are verified for size and SHA-256 before installation. If a saved optional voice is missing, announcements use the included Lessac low voice until it is downloaded. **Test voice** is available only when the selected voice is installed.

Announcements and alerts play in order after their sound. Dismiss, expiry, sleep, and shutdown cancel their audio; higher-priority alerts interrupt it. Weather speech reads the title, instructions and plain-text description while retaining the normal visual alert. Turning off the chime does not turn off separately enabled speech. Reading aloud never submits a read confirmation or safety response.

Speech reads the title and available plain text, up to 2,000 characters and two minutes of audio. Longer text directs the listener to the full notification on screen. Image-only notifications read their heading and prompt the listener to view the screen; include accompanying plain text for the image instructions to be spoken. If speech fails, the notification remains available on screen. Temporary speech files are removed after playback or cancellation.

The installer bundles only the **60 MiB Lessac low model**, its configuration and attribution, and the catalog of optional voices. Optional models and model cards are stored under `%LOCALAPPDATA%\SouthlandServers\SLS_Mass_Notify\voices\`; updates retain them without downloading them again. Voice-specific attribution and use restrictions are documented in [third-party notices](THIRD_PARTY_NOTICES.md). The models are not cleared for unrestricted commercial use.

The installer is approximately **154 MiB**, reduced from 543 MiB with all eight voices bundled.

## PBX compatibility

Existing Basic authentication, endpoint paths, payload schema **1**, and SSE protocol **2** are preserved. Authenticated polling, stream, and receipt requests include:

```http
X-SLS-Client-Version: 1.0.13-beta
X-SLS-Payload-Schema: 1
X-SLS-SSE-Protocol: 2
```

The version comes from the packaged application. A compatible PBX records it against the authenticated desktop identity along with reporting time and connection activity. No heartbeat endpoint, administrator credential, or device fingerprint is added.

Installed and source builds report the version bundled with the app. Basic authentication, certificate verification, and configured HTTPS ports are preserved, including installations on port 8443. Desktop credentials are separate from Control API keys, operator logins, and panic enrollment secrets.

Polling explicitly sends an empty `last_event_id` when establishing a live baseline. The initial request omits `If-None-Match`. `transport_capabilities.preferred` and `sse_available` select the next transport; the response's top-level `transport: "json_poll"` describes that response only. The app follows `poll_interval_seconds` and retains the preference when an unchanged response omits capabilities. Capabilities stay with that PBX/account/enrollment. A remembered SSE retry delay prevents another stream attempt before its deadline. The connection-test button accepts supported polling without opening a disabled stream.

Subsequent requests follow the returned opaque cursor and `has_more`; `events` is authoritative even when `latest` is also present. IDs retain their exact content up to the server's 2,048 UTF-8 byte limit, including Unicode. Cursor gaps, outages, and sleep discard missed broadcasts. Nonadvancing pages stop with a protocol fault instead of looping. An unchanged response leaves popups and saved receipts intact. Switching from negotiation to SSE, and healthy, explicitly requested SSE renewal, continue the current cursor; a real disconnect starts at the live edge.

Polling responses remain limited to 1 MiB. An oversized batch retries the same cursor with fewer events, down to one per page, without replaying a fresh baseline. A single event that still exceeds the limit produces a connection fault instead of bypassing the bound.

Absent, empty, or null optional expiry timestamps are supported, as is a null display timeout. Announcements keep their original publication time and expire at the earliest supplied deadline, positive display timeout, or ten-minute cap. Timeout zero does not remove that cap or override an absolute expiry. Active popups and audio also retain a monotonic deadline so moving the Windows clock backward cannot extend them. Health shows the difference between the PBX's HTTP Date and the computer clock.

Receipts mean **Received by desktop app.** They do not establish human reading, safety, or physical playback. The app requires `ok: true` and the same published event ID before confirming a receipt. Temporary failures keep the original receipt; terminal event rejections remain visible in Health counts without an endless retry loop. A retired connection cannot confirm receipts or revoke a newer account. Changing the PBX's enrollment identity retains old history but does not transfer its unsent receipts to the replacement identity.

### Authenticated images (Labs)

Generated same-origin HTTPS images continue to work without credentials. **🧪 Labs: authenticated images** is off by default in each PBX profile. Enable it only with a qualified PBX that sends `image_authentication: "desktop_basic"` and `/api/sipnotify/desktop/media?event_id=...` on that same HTTPS origin and port. The app selects that alert's account, requires the exact event ID, and blocks authenticated redirects. It never attaches Basic credentials to ordinary image URLs. Both modes enforce the 5 MiB download limit and bounded decoding; written content remains available if an image cannot load.

Offline compatibility tests cover the PBX `0.1.8-beta` desktop, incident, and transport contracts, including nullable expiry and polling/SSE negotiation. Authenticated images remain in Labs until the matching server deployment is qualified. Local Piper notification speech remains a desktop feature and does not fetch PBX paging audio. Desktop enrollment, panic activation, and fleet administration retain their separate authorized contracts.

The server documents [desktop readiness reporting](https://github.com/vipgabe09267/SouthlandServers_Mass_Notify_server/blob/main/docs/DESKTOP_READINESS.md) and [authorized incident responses](https://github.com/vipgabe09267/SouthlandServers_Mass_Notify_server/blob/main/docs/INCIDENT_API.md). Human responses use `/api/sipnotify/desktop/incident` and `/api/sipnotify/desktop/incident/respond` with the configured desktop's Basic credentials. Only explicit supported incident metadata enables those controls. Incident updates and all-clear announcements retain their separate event identities and expiry; they do not cancel previous popups. Enrollment, panic activation, and fleet administration require their own authorized integration.

## Settings and troubleshooting

Per-user settings, history, logs, imported sounds, and update downloads are stored in `%APPDATA%\SouthlandServers\SLS_Mass_Notify\`. Passwords use Windows Credential Manager or user-scoped DPAPI. History defaults to 30 days, and uninstalling preserves per-user data.

Update downloads are optional and disabled by default. Downloads are checked for size and SHA-256; you run the downloaded installer yourself.

| Situation | What to check |
| --- | --- |
| Laptop just woke up | Allow the network to return. The app reconnects automatically and skips missed messages. |
| A new announcement does not appear | Check that monitoring and the PBX profile are enabled, then open **Health**. Send a new announcement after the connection recovers. |
| Connection test passes but nothing appears | Use **Local preview** for display testing or send a new announcement from the PBX. |
| PBX shows a pending receipt | Check the desktop's Health view and server version. Saved receipts retry automatically; the server must link exact-event receipts to delivery results. |
| Support needs details | Use **Export diagnostics**. The report omits credentials, PBX addresses, usernames, and notification bodies. |

## Repository layout

| Location | Contents |
| --- | --- |
| `src/` | Desktop client, installer, transport, presentation, and Windows integration |
| `assets/` | Original SLS logo, Windows icons, and bundled sounds |
| `tests/` | Unit tests and desktop API fixtures |
| `tools/` | Build helpers, dependency checks, and native Windows smoke checks |
| `.github/` | Windows validation, signed-build workflow, and dependency update configuration |
| `build*.ps1` | Windows app and installer build entry points |

Generated output lives in ignored `build/` and `dist/` folders. Windows version resources are generated from `src/sls_version.py`; they are not maintained as duplicate repository files.

## Build and validation

Build on Windows x64 with **CPython 3.14.9** and the **.NET Framework 4.x C# compiler**. Dependencies are pinned with hashes in `requirements-build.txt`.

```powershell
python tools/prepare_workspace_python.py
.\build-installer.ps1 -Clean -PythonExecutable "$PWD\.tools\python-3.14.9\python.exe"
```

The build creates a fresh `.venv-build`, caches the hash-pinned default voice in `.tools/tts`, and stages only Lessac low into `build/tts`. It runs unit tests and native UI/delivery/installer checks and verifies the packaged version, source, and file inventory. It also synthesizes the included voice, downloads optional Amy into an isolated per-user cache, and synthesizes it through the packaged app without playing sound. `-Clean` replaces generated build and distribution output.

Package validation also runs a local preview, a received announcement and a received weather alert through the real inbox, presenter and audio queue. It verifies non-silent PCM, completion of all three messages, reuse of one warmed Piper worker, and intercepted Windows playback so tests stay silent. A full-size file-upgrade fixture checks every resulting file hash, preserves unrelated content, and confirms the unchanged default model was not replaced. This fixture uses temporary folders and mocks machine registration and process control; it does not replace clean-machine deployment testing.

To build without opening any app or installer windows on the current desktop, add `-Headless`. This development-only option runs unit tests and package-integrity checks while skipping desktop smoke checks. It cannot be combined with `-Release`; run full UI validation in a separate Windows test session before releasing.

```powershell
.\build-installer.ps1 -Headless -PythonExecutable "$PWD\.tools\python-3.14.9\python.exe"
```

After a headless build, run the native UI fixtures on a private Windows desktop:

```powershell
.\.venv-build\Scripts\python.exe tools/run_isolated_desktop_checks.py
```

Add `--application "dist/SLS_Mass_Notify/SLS_Mass_Notify.exe"` to check the actual packaged notification windows on the same private desktop, including native overlay order over normal and maximized application windows.

This checks real Settings, setup, notification, and image layouts without showing windows or taking focus on the input desktop. Each fixture runs in its own process job, with logs under `build/isolated-ui/`. It uses temporary installation fixtures and synthetic notifications; it does not change the installed app or contact a PBX. It supplements clean-machine and real-server deployment checks.

The current build pins Python 3.14.9, OpenSSL 3.5.9, Pillow 13.0.0, setuptools 84.2.1, and pip 26.2.2. Package checks require the exact locked dependencies and compare bundled Python, TLS, and SQLite binaries with the reviewed interpreter. Check newly published advisories with `python tools/audit_build_dependencies.py`. Downloaded alert images use only PNG, JPEG, GIF, and WebP decoders, with bounded downloads and pixel counts.

If an upgrade is interrupted, rerun setup. It verifies the protected rollback journal, backup hashes, and destination files before restoring the previous application files. Opening setup and validating a path perform no recovery writes. Unsupported old journals or modified files require administrator review; setup retains their evidence.

Upgrades recognize filename capitalization changes in bundled Windows runtime DLLs. Setup still verifies each installed file against its previous manifest hash before replacing it; a genuinely modified or unowned file is retained for review.

Verified unchanged files, including the large voice models, stay in place during an update. Setup backs up changed files and saves the complete recovery plan once before replacing anything. Recovery checks every planned path, including files an interrupted update had not reached.

Both app and setup include their Tcl/Tk script libraries. The package check constructs setup with its window withdrawn and clears build-time library paths to verify that its UI runtime is self-contained.

```text
dist/
├── SLS_Mass_Notify_Installer.exe     # Distribute this installer
├── SLS_Mass_Notify/
│   ├── SLS_Mass_Notify.exe          # Direct app launch
│   ├── _internal/                  # Keep beside the app EXE
│   └── build-inventory.json
└── packages/                       # Local build/CI output
    ├── SLS_Mass_Notify_Installer.zip
    └── SLS_Mass_Notify_Installer.zip.sha256
```

Run unit tests independently after building:

```powershell
.\.venv-build\Scripts\python.exe -m unittest discover -v
```

<details>
<summary><strong>Managed installation and production release requirements</strong></summary>

For managed installs, run the installer from an elevated process with `--silent --accept-terms`. Optional arguments include `--install-dir`, `--startup on|off`, `--auto-update on|off`, and `--launch`. Use `--silent --update` for updates. Exit codes: `0` success, `740` elevation required, `1603` installation failure, and `3010` reboot required after uninstall.

This is an **unsigned beta**. Production deployment still requires publisher signing, the reviewed runtime update, and clean-machine installation/upgrade/rollback/uninstall validation.

Signed builds require `-Release`, `-SignTool`, `-CertificateThumbprint`, `-TrustedSignerSha256`, and `-TimestampUrl`. Both development and production builds require OpenSSL 3.5.9 or later; the prepared Python runtime includes 3.5.9. Signed packages include a catalog. Verify it with `Get-AuthenticodeSignature` and `Test-FileCatalog`, check the expected signer, and stage deployment files in an administrator-controlled directory.

</details>

## License

[GNU Affero General Public License v3.0](LICENSE) · [Terms of service](TERMS_OF_SERVICE.md)
