# Structured Browser

Allpath's browser tools use a dedicated Playwright profile under
`~/.allpath-agent/browser-profile`. They do not attach to the user's normal
Chrome profile or reuse its cookies.

## MVP tools

- `browser_navigate` opens a public HTTP(S) URL and returns a bounded structured snapshot.
- `browser_snapshot` refreshes page text and interactive element refs such as `e1`.
- `browser_click` clicks one current ref after explicit approval.
- `browser_type` replaces text in one editable ref after explicit approval.

Every top-level navigation, redirect, and HTTP(S) subresource is checked against
resolved IP addresses. Loopback, private, link-local, reserved, multicast,
unspecified, `.local`, `.internal`, credential-bearing, and non-HTTP(S) URLs are
blocked. Data/blob/about subresources created by an already-approved public page
may load, but cannot be used as top-level navigation targets.

Typed browser text is passed to the page but replaced with a character-count
marker in terminal approval previews, SQLite tool executions, SQLite approval
records, and lifecycle events. Downloads are disabled in this first release.

Run `/browser` to inspect runtime readiness. The backend first uses an installed
Google Chrome with Allpath's isolated profile and falls back to Playwright
Chromium. If neither is available, install Chromium with:

```bash
python -m playwright install chromium
```

The complete self-service command surface is:

- `/browser` or `/browser status` — inspect package, browser, and profile readiness.
- `/browser test` — open Example Domain and verify a structured snapshot.
- `/browser install` — request approval, then download Playwright Chromium in the terminal.
- `/browser reset` — request approval, close the session, and remove only Allpath's profile.

You can also say `setup browser`, `connect browser`, `配置浏览器`, or `浏览器状态`
in normal conversation. Allpath responds with the same diagnosis and exact next action.
