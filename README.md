<div align="center">

<img src="assets/SLS_Mass_Notif_App.png" width="144" alt="Southland Servers Mass Notify logo">

# SLS Mass Notify

**Live announcements and weather alerts for Windows desktops.**

The desktop client for [Southland Servers Mass Notify for FreePBX](https://github.com/vipgabe09267/SouthlandServers_Mass_Notify_server).

[**Download the installer · 1.0.11-beta**](https://github.com/vipgabe09267/SouthlandServers_Mass_Notify_app/releases/download/v1.0.11-beta/SLS_Mass_Notify_Installer.exe) · [Release notes](CHANGELOG.md) · [Windows build checks](https://github.com/vipgabe09267/SouthlandServers_Mass_Notify_app/actions/workflows/ci.yml)

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

## What the app does

| Feature | Behavior |
| --- | --- |
| Live delivery | Receives announcements while connected. Messages missed during sleep, shutdown, or disconnection are skipped. |
| Automatic recovery | Reconnects when the network returns. Gives Windows 90 seconds after startup or wake to restore connectivity without connection-error notices. |
| Streaming fallback | Checks for new messages every five seconds if streaming fails. Remembers that fallback for 24 hours. |
| Visual alerts | Displays colored announcements and image-backed weather alerts in one full-size view. Text remains available in **Details** and as the image loading/failure fallback. |
| Expiry | Announcements disappear within ten minutes of publication, or earlier when specified by the sender. Weather alerts retain their published expiry. |
| Receipts | Sends automatic acknowledgements for the exact event ID and retries saved receipts when connectivity returns. |
| Client version | Reports the packaged app version and supported protocols to the PBX on authenticated requests. |
| Tray controls | Provides Settings, History, Health, and Exit. Settings includes sound selection, local preview, and diagnostic export. |

Routine notifications have a single **Dismiss** button. Persistent alerts use **I have read this alert**; that action is stored locally. Automatic receipts confirm software receipt, not human reading or safety. Dismiss does not close a backend incident.

Windows fit the monitor's usable area, including its taskbar. Notices appear at the bottom right of the primary screen, with Settings and Dismiss controls. Notices disappear when their fault clears. Brief recovery failures do not produce an error sound. An outage that continues for five minutes after the recovery period produces one notice. Authentication and configuration faults remain visible in **Health** during recovery.

## PBX compatibility

Existing Basic authentication, endpoint paths, payload schema **1**, and SSE protocol **2** are preserved. Authenticated polling, stream, and receipt requests include:

```http
X-SLS-Client-Version: 1.0.11-beta
X-SLS-Payload-Schema: 1
X-SLS-SSE-Protocol: 2
```

The version comes from the packaged application. A compatible PBX records it against the authenticated desktop identity along with reporting time and connection activity. No heartbeat endpoint, administrator credential, or device fingerprint is added.

The server documents [desktop readiness reporting](https://github.com/vipgabe09267/SouthlandServers_Mass_Notify_server/blob/main/docs/DESKTOP_READINESS.md) and [authorized incident responses](https://github.com/vipgabe09267/SouthlandServers_Mass_Notify_server/blob/main/docs/INCIDENT_API.md). This client sends event receipts; it does not yet submit incident human responses. Enrollment, panic activation, and incident response controls require integration with their separate authorized contracts. Incident state must not be inferred from announcement wording or Dismiss.

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

Build on Windows x64 with **CPython 3.14.7** and the **.NET Framework 4.x C# compiler**. Dependencies are pinned with hashes in `requirements-build.txt`.

```powershell
python tools/prepare_workspace_python.py
.\build-installer.ps1 -Clean -PythonExecutable "$PWD\.tools\python-3.14.7\python.exe"
```

The build creates a fresh `.venv-build`, runs unit tests and native UI/delivery/installer checks, and verifies the packaged version, source, and file inventory. `-Clean` replaces generated build and distribution output.

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

Signed builds require `-Release`, `-SignTool`, `-CertificateThumbprint`, `-TrustedSignerSha256`, and `-TimestampUrl`. The production runtime check requires OpenSSL 3.5.8 or later; the prepared Python runtime contains 3.5.7 and is accepted only for development builds. Signed packages include a catalog. Verify it with `Get-AuthenticodeSignature` and `Test-FileCatalog`, check the expected signer, and stage deployment files in an administrator-controlled directory.

</details>

## License

[GNU Affero General Public License v3.0](LICENSE) · [Terms of service](TERMS_OF_SERVICE.md)
