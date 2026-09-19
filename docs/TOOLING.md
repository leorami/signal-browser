# Export tooling notes

Validated 2026-09-19 against current Signal Desktop export options.

## signalbackup-tools (primary)

- Upstream: [bepaald/signalbackup-tools](https://github.com/bepaald/signalbackup-tools)
- Latest release tag seen: `20260615`; Homebrew `--HEAD` on this machine reported `20250929.150935`
- Desktop database dump is still the reliable primitive:

      signalbackup-tools --dumpdesktopdb signal.sqlite --overwrite

- Useful modifiers: `--desktopdir`, `--ignorewal`, `--desktopkey`, `--showdesktopkey`
- `--exportdesktophtml` exists in some docs/builds, but the installed HEAD help text does not advertise it. This project therefore dumps SQLite and builds its own viewer.
- Install (macOS): `brew tap bepaald/signalbackup-tools https://github.com/bepaald/signalbackup-tools && brew install --HEAD signalbackup-tools`

## Internal attachment decrypt (primary for media)

Signal Desktop attachment v2 (current `message_attachments.localKey`):

- `localKey` is Base64 of 64 bytes: AES-256 key || HMAC-SHA256 key
- File layout: 16-byte IV || ciphertext || 32-byte HMAC
- Verify HMAC over IV+ciphertext, AES-CBC decrypt, strip PKCS#7
- Also consume thumbnail/screenshot columns when present

Older fallbacks (GCM `nonce|ct|tag`, 32-byte CBC) remain for leftover blobs.

## sigtop (optional fallback)

- Upstream: [tbvdm/sigtop](https://github.com/tbvdm/sigtop)
- Strengths: attachment export (`sigtop export-attachments`) and Keychain/safe-storage DB unlock
- macOS install: `brew install --HEAD tbvdm/tap/sigtop`
- Used only if `signalbackup-tools` is unavailable, or as an optional attachment helper

## Signal Desktop built-in export

Signal Desktop can write a plaintext chat-history folder (`metadata.json`, `main.jsonl`, `files/`). That is a shareable archive, not a one-click local backup. This app reads the live Desktop data directory instead so users never leave the app to export.

## Decision

1. Dump Desktop SQLite with `signalbackup-tools`
2. Decrypt and catalog media in-process
3. Store the result in a passphrase-encrypted local vault
4. Fall back to `sigtop` for the DB dump when needed
