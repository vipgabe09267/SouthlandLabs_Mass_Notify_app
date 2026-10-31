<div align="center">

<img src="assets/mass-notify-app.png" width="144" alt="Southland Labs Mass Notify icon">

# Southland Labs Mass Notify

**Live announcements and weather alerts for Windows desktops.**

[Download 1.0.14-beta](https://github.com/vipgabe09267/SouthlandLabs_Mass_Notify_app/releases/download/v1.0.14-beta/SLL_Mass_Notify_Installer.exe) | [Release notes](CHANGELOG.md) | [Project website](https://southlandlabs.dev/projects/mass-notify/app) | [Build checks](https://github.com/vipgabe09267/SouthlandLabs_Mass_Notify_app/actions/workflows/ci.yml)

</div>

The Windows receiver for [Southland Labs Mass Notify Server](https://southlandlabs.dev/projects/mass-notify/server). It displays new notifications from your configured PBX and can read announcements and weather alerts aloud using local Piper speech.

**1.0.14-beta** brings the Southland Labs name, artwork, and desktop colors. It fixes invisible text-field cursors, improves layouts at 100-200% scaling, and prevents speech from stopping before the audio device finishes playback.

## Install or upgrade

Requires **Windows x64**, administrator access to install, and desktop credentials supplied by your PBX administrator. Python is included.

1. Download **SLL_Mass_Notify_Installer.exe** and run it.
2. Open **Southland Labs Mass Notify** from the Start Menu.
3. Enter the PBX's **HTTPS address**, desktop username, and password in Settings, then save.
4. Select **Test connection** to check connectivity. Use **Local preview** to check the notification window and audio.
5. Send a new desktop announcement from the PBX to verify delivery.

**Upgrading from 1.0.13 or earlier:** download and run this installer manually. Earlier clients validate the previous repository and installer names and may not offer the renamed package through update checks. Setup recognizes the existing installation and preserves settings, saved credentials, History, downloaded voices, and installation preferences.

The release has one uploaded asset: the installer EXE, approximately **154 MiB**. GitHub's automatic source ZIP/TAR archives are for developers.

## Notifications

| Feature | Behavior |
| --- | --- |
| Live delivery | Receives new announcements while connected. Messages missed during sleep, shutdown, or disconnection are skipped. |
| Clear display | Notifications stay above other application windows and show **URGENT** or **Regular**, with tests labeled separately. Windows fit the monitor's usable area above the taskbar. |
| Colored alerts | Displays one visual announcement or weather image. Written content remains in **Details** and appears as a fallback if the image cannot load. |
| Multiple PBXs | Supports up to three profiles. Notifications and History show the configured PBX name. |
| Automatic recovery | Reconnects after sleep and network changes. Allows 90 seconds for networking to recover before routine connection-error notices. |
| History and Health | Provides notification history, connection status, receipt counts, and diagnostic export from the tray. |
| Delivery receipts | Automatically acknowledges the exact event received by the app. This confirms software receipt, not human reading or safety. |
| Incident responses | On a compatible PBX, **Respond to incident** offers authorized read, safe, and assistance responses from the notification or History. |

Announcements expire within ten minutes of publication, or earlier if the sender specifies a deadline. Weather alerts retain their published expiry. Routine messages have one **Dismiss** action; persistent alerts use **I have read this alert**, recorded locally. Closing or dismissing a popup does not submit a human response or close a server incident.

An incident response is confirmed only after the PBX accepts it. Unconfirmed requests remain available in History for a deliberate **Retry** using the same request ID. Human responses are never retried automatically.

## Speech and voices

In **Settings > Notification sound**, use **Read announcements and alerts aloud (Piper)** to enable speech and select a voice. **English (US) / Lessac / low** is included and enabled by default.

Seven voices are optional downloads: Amy low, Lessac medium, Ryan low, French Siwis medium, German Thorsten low, Portuguese (Brazil) Faber medium, and Spanish Davefx medium. Select a voice and choose **Download voice**; progress and cancellation are available. Each optional voice is about **60 MiB**. Voices change pronunciation, not the message's language.

- **Test voice** reads a sample using the selected installed voice, without a chime or PBX connection.
- **Play sound** previews only the selected notification chime.
- **Local preview** checks the notification window and audio together.

Speech is prepared while the chime plays. A warm Piper worker keeps the selected voice loaded between messages. Playback waits for Windows to report completion rather than stopping on a duration timer. Dismiss, expiry, sleep, shutdown, and higher-priority alerts still stop speech; playing a chime preview does not replace the speech output.

Installed voices work offline. Notification text is never sent to a speech service. Voice downloads use pinned HTTPS sources and exact-size/SHA-256 checks, without PBX credentials or announcement text. If an optional voice is missing, notifications use the included Lessac low voice; **Test voice** requires the selected voice to be installed.

Speech reads available plain text, up to 2,000 characters and two minutes of audio. Image-only notifications read their heading and direct the listener to the screen. If speech fails, the visual notification remains available. Reading aloud never submits a read confirmation or safety response.

Voice attribution and use restrictions are listed in [third-party notices](THIRD_PARTY_NOTICES.md). The models are not cleared for unrestricted commercial use.

## Connections and stored data

Use credentials assigned to this desktop, not an administrator account, Control API key, or panic enrollment secret. HTTPS certificate verification and explicitly configured ports, including **8443**, are preserved. The app follows the PBX's polling or SSE preference and reports its packaged version on authenticated requests.

Settings, History, logs, imported sounds, and optional update downloads remain under `%APPDATA%\SouthlandServers\SLS_Mass_Notify\`. Downloaded voices remain under `%LOCALAPPDATA%\SouthlandServers\SLS_Mass_Notify\voices\`. These existing paths and credential identifiers are retained for upgrade compatibility. Passwords use Windows Credential Manager or user-scoped DPAPI. Uninstalling preserves per-user data; History normally retains 30 days.

Update downloads are optional and disabled by default. Downloaded installers are checked for size and SHA-256 and require administrator deployment. Setup replaces only manifest-owned files, retains unchanged voice models, and journals file, shortcut, and uninstall-registration changes for interrupted-upgrade recovery.

<details>
<summary><strong>Desktop API compatibility</strong></summary>

Existing Basic authentication, endpoint paths, payload schema **1**, and SSE protocol **2** remain unchanged. Authenticated polling, streaming, and receipt requests include these legacy protocol header names:

```http
X-SLS-Client-Version: 1.0.14-beta
X-SLS-Payload-Schema: 1
X-SLS-SSE-Protocol: 2
```

The app starts with an authenticated polling baseline and follows `transport_capabilities.preferred`, `sse_available`, and `poll_interval_seconds`. It retains capabilities when an unchanged response omits them, follows opaque cursors through every `has_more` page, and respects stream retry delays. Genuine disconnections establish a fresh live baseline; planned SSE renewal retains its cursor.

Polling responses are bounded to 1 MiB. Oversized batches retry the same cursor with fewer events; a single oversized event fails rather than bypassing the limit. Event identifiers retain their exact content up to 2,048 UTF-8 bytes. Nullable expiry fields are supported; the earliest deadline and ten-minute announcement cap still apply.

Receipts require `ok: true` and the matching published event ID. Temporary failures retry within a bounded queue; terminal rejections remain visible in Health. Cursors, receipts, history, and in-flight responses stay scoped to the exact PBX origin, account, and enrollment. Explicit human responses use `/api/sipnotify/desktop/incident` and `/api/sipnotify/desktop/incident/respond` with the authorized desktop credentials.

**Labs: authenticated images** is disabled by default per profile. It requires explicit `image_authentication: "desktop_basic"`, the exact event ID, and the same HTTPS origin, port, and `/api/sipnotify/desktop/media` path. Authenticated redirects are blocked; ordinary images never receive Basic credentials. Image downloads are limited to 5 MiB and bounded PNG, JPEG, GIF, and WebP decoding.

Compatibility fixtures cover the PBX `0.1.8-beta` desktop and incident contracts. Authenticated images require a qualified matching server deployment. Enrollment, panic activation, fleet administration, incident updates, and all-clear retain their separate authorized contracts; the client does not infer them from message wording.

</details>

## Troubleshooting

| Situation | What to check |
| --- | --- |
| Laptop just woke up | Allow networking to return. The app reconnects automatically and skips missed broadcasts. |
| A new announcement does not appear | Check monitoring and the PBX profile are enabled, then open **Health**. Send a new announcement after reconnection. |
| Connection test passes but no popup appears | The connection test sends no notification. Use **Local preview** or send a new announcement from the PBX. |
| Speech is missing | Check the Piper toggle, selected voice download, output device, and **Test voice**. Turning off the chime does not disable separately enabled speech. |
| PBX shows a pending receipt | Check Health and server compatibility. The server must link the exact-event receipt to its delivery result. |
| Support needs details | Use **Export diagnostics**. The report omits credentials, PBX addresses, usernames, and notification bodies. |

## Build and validation

Build on Windows x64 with **CPython 3.14.9** and the **.NET Framework 4.x C# compiler**. Dependencies and voice assets are pinned with hashes.

```powershell
python tools/prepare_workspace_python.py
.\build-installer.ps1 -Clean -Headless -PythonExecutable "$PWD\.tools\python-3.14.9\python.exe"
.\.venv-build\Scripts\python.exe tools/run_isolated_desktop_checks.py --application "dist/SLL_Mass_Notify/SLL_Mass_Notify.exe"
```

The headless build runs automated tests and package checks without visible windows. The second command runs native Settings, setup, delivery, and notification checks on a private Windows desktop without taking focus. Logs are written under `build/isolated-ui/`. Omit `-Headless` for the standard build's desktop checks; it cannot be combined with `-Release`.

**1.0.14-beta validation:** 474 automated tests, private Windows UI checks at 100-200% scaling, installed upgrade checks, and rollback/uninstall fixtures. Speech checks validate real Piper PCM through its final frames with simulated delayed device completion; native Windows completion and cancellation were separately checked using digital silence. Tests do not send PBX announcements or play audible speech.

Package verification checks the executable version and Southland Labs metadata, source bytecode, complete file inventories, bundled runtime libraries, and installer payload. Windows version resources come from `src/sll_version.py`. Run dependency checks with `python tools/audit_build_dependencies.py` and unit tests with `.\.venv-build\Scripts\python.exe -m unittest discover -v`.

```text
dist/
|-- SLL_Mass_Notify_Installer.exe     # Distribute this installer
|-- SLL_Mass_Notify/
|   |-- SLL_Mass_Notify.exe          # Direct launch; keep _internal beside it
|   |-- _internal/
|   `-- build-inventory.json
`-- packages/                       # Local build/CI ZIP and checksum
```

Source is in `src/`, artwork and sounds in `assets/`, tests in `tests/`, and build helpers in `tools/`. Generated `build/` and `dist/` output is ignored by Git.

<details>
<summary><strong>Managed installation and signing</strong></summary>

For managed installs, run setup elevated with `--silent --accept-terms`. Optional arguments include `--install-dir`, `--startup on|off`, `--auto-update on|off`, and `--launch`; updates can use `--silent --update`. Exit codes are `0` success, `740` elevation required, `1603` installation failure, and `3010` reboot required after uninstall.

If an upgrade is interrupted, rerun setup. Recovery validates the protected journal, owned files, shortcut snapshots, and uninstall registration before restoring prior state. Modified or unowned files are retained for administrator review.

This release is an **unsigned beta**. Production deployment requires publisher signing and clean-machine installation, upgrade, rollback, and uninstall qualification. Signed builds require `-Release`, `-SignTool`, `-CertificateThumbprint`, `-TrustedSignerSha256`, and `-TimestampUrl`. The build requires the reviewed Python 3.14.9 runtime with OpenSSL 3.5.9 and checks the exact dependency lock. Signed packages include a catalog for `Get-AuthenticodeSignature` and `Test-FileCatalog` verification.

</details>

## License

[GNU Affero General Public License v3.0](LICENSE) | [Terms of service](TERMS_OF_SERVICE.md)
