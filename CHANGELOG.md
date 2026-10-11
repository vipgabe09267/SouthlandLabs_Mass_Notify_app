# Changelog

## 1.0.11-beta - 2026-10-11

- Give Windows 90 seconds after startup or wake to restore networking without connection-error notices. Reset transient fault timers after sleep and keep automatic reconnection and receipt retries.
- Remove queued and visible notices when their fault clears. Sustained outages still produce a notice; credential, TLS, and local storage faults are retained for review.
- Place notices at the bottom right above the primary taskbar. Replace fixed canvas text with wrapped content and visible Settings/Dismiss controls, and remove error beeps.
- Preserve live-only delivery and discard old sockets and queued announcements after wake.
- Organize application source into `src/` and original artwork/sounds into `assets/`. Generate Windows version resources in the build folder instead of tracking duplicate metadata.
- Rewrite the README with installation steps, behavior and compatibility tables, troubleshooting, and build instructions. Keep release downloads limited to the installer EXE.

## 1.0.10-beta - 2026-10-01

- Report the bundled app version, payload schema 1, and SSE protocol 2 on authenticated desktop polling, live-stream, and exact-event receipt requests.
- Display image-backed weather alerts in the same full-size layout as colored announcements, without duplicate raw text. Keep readable text as the loading/failure fallback and in Details.
- Preserve weather severity, absolute expiry, explicit test markers, and local read status. Automatic app receipts remain separate from human read confirmations and Dismiss.

## 1.0.9-beta - 2026-09-21

Changes since 1.0.8-beta:

- Fixed successive announcements failing to arrive when live streaming stalls. Added polling fallback and automatic receipt retries.
- Skipped announcements missed while asleep or disconnected. Queued and visible announcements now expire within ten minutes of publication.
- Fixed blank colored announcements and duplicate plain text. Kept Dismiss visible, resized images to fit, and restored the SLS window icon.
- Fixed Settings and installer windows extending below the taskbar, including at larger text sizes.
- Replaced setup with one self-contained installer EXE. Fixed ownership and Start Menu permission errors, unresponsive installation, and upgrades blocked by lingering app processes.
- Added local history, connection health, diagnostic export, and separate connection-test and local-preview controls.
- Improved credential storage, media validation, upgrade rollback, and update download verification. Update downloads support installer EXEs and are not automatically run.

This is an unsigned beta. The server's pending-receipt display requires a separate backend fix. See the [README](README.md) for setup and remaining limitations.
