/**
 * The whole extension, essentially: one context-menu item.
 *
 * There is no content script and nothing that reads a page. The user selects
 * text and invokes the lookup themselves, which is the distinction
 * REQUIREMENTS §6 rests on — a content script reading messages is the
 * automated collection Discord's terms prohibit, and this is not that.
 *
 * Note what this file does *not* touch. `OnClickData` also carries `pageUrl`
 * and `frameUrl`, and the listener is handed a `tab` with its `url` and
 * `title`. None of them are read. Rule 16 says only the selected term leaves
 * the browser, and the way to keep that true is to never put the rest in a
 * variable in the first place.
 */

const MENU_ID = 'slang-lookup';

/**
 * Mirrors MAX_SELECTION_CHARS in src/server/api.ts.
 *
 * Checked here as well as there so that selecting a whole article and
 * right-clicking it never becomes a request at all — the page should not
 * leave the browser even as far as loopback.
 */
const MAX_SELECTION_CHARS = 300;

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    // %s is the selection; Chrome truncates it in the menu label for us.
    title: 'What does “%s” mean?',
    contexts: ['selection'],
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId !== MENU_ID) return;

  const selection = (info.selectionText ?? '').trim();
  if (selection === '') return;

  const query =
    selection.length > MAX_SELECTION_CHARS
      ? { tooLong: '1', q: '' }
      : { tooLong: '', q: selection };

  const params = new URLSearchParams(query);
  void chrome.windows.create({
    url: chrome.runtime.getURL(`result.html?${params.toString()}`),
    type: 'popup',
    width: 460,
    height: 340,
  });
});
