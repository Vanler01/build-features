# Slang Translator — Chrome extension

Select text, right-click, get a definition. Personal use, unpublished
(CLAUDE.md rule 18).

## Running it

```bash
npm run build:extension     # compiles extension/src/*.ts → extension/dist/*.js
npm run serve               # the backend, on 127.0.0.1:8787
```

The backend must be running for lookups to work. It holds the Claude key; the
extension holds no keys at all (rule 17).

### Firefox, Zen, LibreWolf (Firefox 121+)

`about:debugging#/runtime/this-firefox` → **Load Temporary Add-on…** → pick
`extension/manifest.json` (the manifest file itself, not the folder).

Temporary add-ons are removed when the browser restarts, so this is a
re-do-it-each-session affair unless you sign the extension. After a rebuild,
press **Reload** on the add-on's card.

### Chrome, Edge, Brave (Chrome 121+)

`chrome://extensions` → enable **Developer mode** → **Load unpacked** → select
the `extension/` **directory**. Reload from the extension's card after a
rebuild.

### Safari

Not supported as-is. Safari only loads web extensions that have been converted
into an Xcode project (`xcrun safari-web-extension-converter`) and signed. That
is a real amount of machinery for a personal tool — use Firefox or Chrome.

### One manifest, both engines

Firefox has no service-worker background; it uses an event page. The manifest
declares **both** `background.scripts` and `background.service_worker`, which
works because Chrome 121+ ignores `scripts` in MV3 and Firefox 121+ ignores
`service_worker`. Below those versions each browser rejects the other's key,
which is what `strict_min_version` records.

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
- **One `host_permissions` entry**, and it is loopback:
  `http://127.0.0.1:8787/*`. This is a real deviation from rule 15's "no
  host_permissions list", recorded rather than glossed over.

  It was not there when the extension targeted Chrome alone, where the
  server's CORS headers are enough. Firefox's MV3 cross-origin handling is
  documented as unreliable for extension pages fetching localhost even with
  correct CORS, and `host_permissions` is the dependable route there. The
  entry grants access to one port on your own machine — not to a website, not
  to a list of sites, and nowhere near `<all_urls>`. Rule 15's purpose is that
  the extension cannot reach the web; this does not give it that.

  The server still enforces its own CORS policy independently, granting only
  `chrome-extension://`, `moz-extension://` and `safari-web-extension://`
  origins, and still sends `Access-Control-Allow-Private-Network: true` for
  Chrome's private-network preflight.

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
