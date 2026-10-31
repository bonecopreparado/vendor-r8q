# GoFile delivery helper

Official source reviewed: [GoFile API](https://gofile.io/api), documentation
indexed as last updated May 16, 2025, checked October 31, 2026. The current
documented upload endpoint is `POST https://upload.gofile.io/uploadfile` with
multipart field `file`. It routes to the closest region; documented regional
proxies are also under `gofile.io`. An upload without token/folder parameters
creates a guest account and a public folder. `Authorization: Bearer` is supported
for an existing account token. No account token is needed for the initial guest
upload. This is an API upload, not an API listing/direct-link call.

The legacy `/servers` discovery and `{server}/contents/uploadfile` examples found
elsewhere are not used: the current official document recommends the global
upload endpoint and does not document server discovery. This prevents depending
on a legacy API only to choose a destination. Nonofficial clones using `.my`,
`.is`, or other domains were not treated as sources for the `.io` service.

`ci-r8q/tools/gofile_upload.py` uses Python standard library, the inherited proxy
and CA settings, and HTTPS to the official domain only. An optional `GOFILE_TOKEN`
is sent only as an Authorization header. Account/guest tokens and raw API JSON
are discarded from outputs. Download links must be canonical `https://gofile.io/d/`
share links. Local size/SHA256 are emitted; server size and MD5, when returned,
must agree. A local SHA256 after the request detects an artifact changed during
upload. Uploads are limited to compressed CI artifacts of at most 128 MiB; the
helper does not send full ROM images. Socket timeout is capped at 60 seconds,
default 45 seconds. Redirects outside GoFile HTTPS are refused.

`--summary "$GITHUB_STEP_SUMMARY"` appends a public download link and SHA256.
`--result upload.json` writes only public metadata. Without `--strict`, upload
failure returns zero so the GitHub artifact remains the delivery fallback.
It prints a controlled diagnostic without raw remote error details. Root workflow
should publish the GitHub artifact independently before this optional mirror.

No upload was attempted in this environment. The parent reported an unavailable
execution proxy. The helper was validated with mocked HTTP/transport only; this
does not prove that a GoFile upload will succeed from a GitHub runner.

Validation: 15 tests pass with no network access, including multipart request,
guest/authenticated upload, bounded HTTP response/timeout, sanitized errors,
file mutation, size/type limits, URL restrictions, metadata digests and default
best-effort/strict CLI behavior.
