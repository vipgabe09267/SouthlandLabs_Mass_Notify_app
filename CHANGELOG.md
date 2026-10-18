# Changelog

## 1.0.12-beta - 2026-10-17

- Prepare announcement speech while the notification chime is playing, instead of adding synthesis time after the chime. Add a dedicated Test voice control with preparation/playback status and private diagnostic timings.
- Verify local preview and a normal announcement through the packaged presenter, audio queue, child synthesis, non-silent PCM, and intercepted Windows playback calls. Voice model synthesis alone is no longer the only speech integration check.
- Verify unchanged installed files but leave them in place. Back up only files that need replacement and persist the complete recovery plan once, avoiding a growing journal rewrite and disk flush for every file. Keep rollback, interrupted-upgrade recovery, missing-file repair, and modified-file rejection.
- Exercise a full application-and-voice upgrade in an isolated fixture, verify every installed hash, and confirm all eight unchanged models keep their file identities. Record phase timings without touching the machine's registry, shortcuts, or running client.

- Fix upgrades rejecting unchanged Microsoft runtime DLLs when the new package changes filename capitalization. Preserve one manifest entry per Windows path, verify the previous hash, and retain rollback and interrupted-upgrade recovery.
- Wrap installer status messages and let the terms/log panels fit the available width, so long error paths do not stretch setup horizontally.
- Bundle Tcl/Tk initialization scripts explicitly. Verify setup can construct its hidden UI without relying on the build machine's library paths, including during headless validation.
- Add offline Piper speech for announcements, enabled by default. Add a Settings toggle and eight bundled voices: Lessac low (default), Amy low, Lessac medium, Ryan low, French Siwis medium, German Thorsten low, Portuguese Faber medium, and Spanish Davefx medium.
- Serialize announcement sounds and speech, stop dismissed or expired messages, and let higher-priority alerts interrupt audio. Keep synthesis off the UI thread in a hidden, time-limited process. Speech never submits a receipt, read confirmation, or safety response.
- Pin the speech dependencies, voice model hashes, configurations, and attribution files. Check real synthesis with every packaged voice without opening a window or playing sound. Raise bounded installer/download size limits to accommodate the eight offline models; retain hash and exact-size verification.
- Switch immediately to authenticated live polling when the PBX rejects streaming with `stream_capacity_reached`. Avoid the five-minute connection gap when its PHP-FPM streaming pool is full. Keep the normal retry delay for other rate-limit errors and preserve live-only delivery.
- Fix SSE control-block IDs leaking into the next notification's explicit identity.
- Keep update checks safe while the UI opens and closes critical alerts; cover the real presenter state in update tests.
- Recover hash-verified installer files after an interrupted upgrade while refusing changed, unowned, or out-of-root content.
- React to native Windows suspend/resume and IPv4/IPv6 address changes. Fence stale connections immediately, preserve revoked credentials, and reconnect from the live edge without blocking the UI on socket shutdown.
- Add explicit incident responses from alerts and History using the desktop-authorized PBX API. Keep human responses separate from automatic receipts and Dismiss. Save request IDs before sending and reuse them on deliberate retries after an uncertain result.
- Keep setup path validation read-only. Recover interrupted files only during an elevated installation after stopping the app, and preserve recovery evidence on verification failures.
- Add a headless development build mode that runs unit and package-integrity checks without launching app or installer windows. Production builds still require full validation.
- Fix Windows PowerShell builds aborting on successful native-tool progress written to stderr; use the actual process exit code to determine failure.

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
