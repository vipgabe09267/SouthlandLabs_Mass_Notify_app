# Changelog

## 1.0.14-beta - 2026-10-30

- Wait for Windows audio-device completion before marking speech finished or removing its WAV file, preventing the final words from being cut off by a duration timer. Keep speech output separate from chime previews, while retaining Dismiss, expiry, shutdown, and urgent-alert interruption.
- Rebrand the desktop client and installer as Southland Labs Mass Notify, using the project website's logo, icon, and color palette. Update application metadata, repository documentation, and distribution names.
- Make the text insertion cursor visible in editable fields and retain readable focus and selection colors in the new theme.
- Keep the Settings header and setup controls within the available screen at 100–200% scaling. Improve text contrast when a colored notification's image cannot load.
- Upgrade existing installations in place, replace only owned old shortcuts and executables, and retain settings, saved credentials, History, downloaded voices, and installation preferences. Recover shortcut and uninstall-registration changes after an interrupted upgrade as well as application files.
- Continue bounded cleanup of cached installers saved before the rebrand. Earlier clients need a one-time manual upgrade because the repository and installer filenames have changed.
- Preserve existing PBX protocol names and authenticated desktop contracts during the rebrand.

## 1.0.13-beta - 2026-10-25

- Restore always-on-top display for regular announcements as well as urgent alerts. Show the priority as `URGENT` or `Regular` on plain and image-backed notifications, retaining a separate test marker and existing dismissal/expiry rules. Verify native Windows z-order against a normal application raised afterward.
- Read received weather alerts as well as announcements. Prioritize weather instructions, retain explicit test markers, and read image-only headings with a prompt to view the notification. The existing speech toggle controls both categories.
- Warm one hidden Piper worker when speech is enabled and reuse its loaded voice between messages. Remove repeated interpreter/model startup delays, retain voice selection and fallback, and stop or restart the worker on cancellation, failure, timeout, or app shutdown. No notification text leaves the device.
- Verify speech through the actual received-payload, durable inbox, presentation and audio paths for an announcement and weather alert, plus a local preview. Require all three to finish through intercepted playback using the same warmed process; record synthesis timings without message text.
- Update the bundled runtime to Python 3.14.9 with OpenSSL 3.5.9. Update Pillow to 13.0.0, setuptools to 84.2.1, and pip to 26.2.2, retaining reviewed hashes and checking current dependency advisories.
- Restrict downloaded notification images to PNG, JPEG, GIF, and WebP. Keep dimension, pixel-count, and download limits and show the text fallback for unsupported or damaged images.
- Keep the notification dispatcher running after a transient local storage failure. Reject incident responses from retained windows after enrollment replacement, including replies that arrive after replacement.
- Preserve the original incident notification in History while its explicit human response is unconfirmed, so retention cleanup cannot remove the only route to retry the saved request. Resume normal retention after confirmation and keep this protection scoped to the original enrollment.
- Prevent malformed JSON and oversized SSE retry values from interrupting later valid events. Require real heartbeat or notification activity to keep a stream alive; blank padding cannot hide a stalled connection.
- Interrupt optional voice downloads promptly on cancellation and enforce absolute header and total download deadlines, including servers that trickle bytes without triggering socket timeouts.
- Add a private Windows desktop runner for native setup, layout, image, and delivery checks. It never switches the input desktop, contains each fixture's child processes, and writes failures to local build logs.
- Negotiate transport through an authenticated polling baseline. Honor the PBX's documented polling/SSE preference and polling interval; retain capabilities when unchanged replies omit them. Keep PHP-FPM on healthy polling, respect the stream's retry deadline, and accept polling in connection tests without requiring an SSE slot.
- Drain every page of a live polling burst using the server's opaque cursor. Establish an explicitly empty baseline after startup or disconnection, skip retained history on cursor gaps, and detect nonadvancing pagination. Keep unchanged responses from replaying `latest` or clearing delivery state.
- Reduce polling page size when a batch exceeds the 1 MiB response limit, retrying the same cursor without treating the connected session as a new baseline. Keep the size limit and stop if even a single-event page exceeds it.
- Fence late polling and receipt replies after account, credential, enrollment, or connection changes. Bind local delivery records to the PBX's reported enrollment identity without transferring another enrollment's receipts.
- Continue the current cursor during an explicitly requested healthy SSE renewal. Keep fresh live baselines for actual disconnections and cursor resets.
- Accept null display timeouts and optional expiry timestamps. Apply the earliest original deadline consistently to storage, presentation, and audio; enforce the ten-minute announcement cap even with timeout zero. Retain monotonic deadlines for active popups and audio.
- Honor numeric and HTTP-date Retry-After values for rate limits and service outages. Bound saved receipt retries, process receipt batches, and retain terminal rejections for administrator review. Never invent a published event ID for an acknowledgement.
- Preserve weather instructions and message type, give explicit `is_test` precedence over legacy test metadata, and respect `beep: no` without disabling independently configured announcement speech.
- Show the configured PBX name on alerts and in notification history. Keep written descriptions and instructions in Details, and expose server clock differences in Health.
- Add per-PBX **🧪 Labs** support for authenticated event images, off by default. Restrict credentials to that enrollment's exact HTTPS origin, port, media path, and event ID; block authenticated redirects and enforce the 5 MiB image limit.
- Support the server's 2,048-byte UTF-8 event identifiers without rewriting them. Preserve Unicode cursors on polling and streaming requests, keep receipt JSON below the request limit, and allow bounded escaped receipt confirmations. Accept larger nonnegative server display timeouts while retaining the desktop's ten-minute cap.
- Add private compatibility fixtures for transport negotiation, polling-to-SSE handoff, bursts, live baselines, stale responses, enrollment replacement, exact-event receipts, expiry, sound instructions, and image credential isolation.

## 1.0.12-beta - 2026-10-17

- Bundle only Lessac low in the installer. Offer seven optional voice downloads in Settings, with progress, cancellation, pinned HTTPS sources, exact-size and SHA-256 checks, and per-user storage preserved across app upgrades. Keep announcements working with Lessac when an optional voice is missing; test downloaded Amy through the packaged synthesizer.
- Prepare announcement speech while the notification chime is playing, instead of adding synthesis time after the chime. Add a dedicated Test voice control with preparation/playback status and private diagnostic timings.
- Verify local preview and a normal announcement through the packaged presenter, audio queue, child synthesis, non-silent PCM, and intercepted Windows playback calls. Voice model synthesis alone is no longer the only speech integration check.
- Verify unchanged installed files but leave them in place. Back up only files that need replacement and persist the complete recovery plan once, avoiding a growing journal rewrite and disk flush for every file. Keep rollback, interrupted-upgrade recovery, missing-file repair, and modified-file rejection.
- Exercise a full application-and-default-voice upgrade in an isolated fixture, verify every installed hash, and confirm the unchanged model keeps its file identity. Record phase timings without touching the machine's registry, shortcuts, or running client.
- Fix upgrades rejecting unchanged Microsoft runtime DLLs when the new package changes filename capitalization. Preserve one manifest entry per Windows path, verify the previous hash, and retain rollback and interrupted-upgrade recovery.
- Wrap installer status messages and let the terms/log panels fit the available width, so long error paths do not stretch setup horizontally.
- Bundle Tcl/Tk initialization scripts explicitly. Verify setup can construct its hidden UI without relying on the build machine's library paths, including during headless validation.
- Add offline Piper speech for announcements, enabled by default. Add a Settings toggle and eight voice choices: included Lessac low (default), plus optional Amy low, Lessac medium, Ryan low, French Siwis medium, German Thorsten low, Portuguese Faber medium, and Spanish Davefx medium.
- Serialize announcement sounds and speech, stop dismissed or expired messages, and let higher-priority alerts interrupt audio. Keep synthesis off the UI thread in a hidden, time-limited process. Speech never submits a receipt, read confirmation, or safety response.
- Pin the speech dependencies, voice model hashes, configurations, and attribution files. Check real synthesis with the included voice and an optional downloaded voice without opening a window or playing sound. Retain bounded installer/download sizes, hash and exact-size verification.
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
- Fixed blank colored announcements and duplicate plain text. Kept Dismiss visible, resized images to fit, and restored the application window icon.
- Fixed Settings and installer windows extending below the taskbar, including at larger text sizes.
- Replaced setup with one self-contained installer EXE. Fixed ownership and Start Menu permission errors, unresponsive installation, and upgrades blocked by lingering app processes.
- Added local history, connection health, diagnostic export, and separate connection-test and local-preview controls.
- Improved credential storage, media validation, upgrade rollback, and update download verification. Update downloads support installer EXEs and are not automatically run.

This is an unsigned beta. The server's pending-receipt display requires a separate backend fix. See the [README](README.md) for setup and remaining limitations.
