# Slang Translator — Chrome extension

Select text, right-click, get a definition. Personal use, unpublished
(CLAUDE.md rule 18).

## Running it

```bash
npm run build:extension     # compiles extension/src/*.ts → extension/dist/*.js
npm run serve               # the backend, on 127.0.0.1:8787
```

Then in Chrome: `chrome://extensions` → enable **Developer mode** → **Load
unpacked** → select this `extension/` directory. Rebuild and hit reload on the
extension card after changing anything under `src/`.

The backend must be running for lookups to work. It holds the Claude key; the
extension holds no keys at all (rule 17).

## Permissions, and why there are so few

```json
"permissions": ["contextMenus"]
```

That is the entire list. No `host_permissions`, no `activeTab`, no
`content_scripts`, and emphatically no `<all_urls>` (rule 15).

- **No content script.** Nothing reads any page. `contextMenus.onClicked`
  hands us `selectionText` directly, on a selection the user made and a menu
  item the user clicked. That is the distinction REQUIREMENTS §6 rests on: a
  content script reading messages is the automated collection Discord's terms
  prohibit, and this is not that.
- **No `activeTab`.** Rule 15 permits it; we found we never need it, because
  we never touch the page. Shipping tighter than the rule allows.
- **No `host_permissions`.** The fetch to the backend is authorised by the
  server's CORS policy, which grants only `chrome-extension://` origins. The
  server also sends `Access-Control-Allow-Private-Network: true`, because a
  request to a loopback address is a "private network request" and Chrome can
  refuse the preflight without it. Extension origins appear exempt from that
  check today, but the classification is undocumented and can change.

  If a future Chrome blocks the request anyway, the minimal fix is a single
  narrow entry — `"host_permissions": ["http://127.0.0.1:8787/*"]` — and not a
  wildcard. Loopback only, never a site.

## What leaves the browser

The selected text, and nothing else (rule 16).

`OnClickData` also carries `pageUrl` and `frameUrl`, and the listener is handed
a `tab` with its `url` and `title`. `background.ts` reads none of them — the
way to keep "only the term leaves" true is to never put the rest in a variable.

Selections over 300 characters are refused before any request is made. "Only
the term, never the page" is otherwise defeated by pressing Ctrl+A and
right-clicking.

## Sharing it

Don't, yet. Rule 18 holds: unpublished and personal-use until each target
platform's terms have been reviewed individually. Sharing also turns the
loopback backend into a hosted service, which needs auth, rate limiting and an
abuse story it does not currently have.
