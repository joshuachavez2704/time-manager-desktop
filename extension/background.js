// Match this host/port to the server defined in src/tracker.py
// (tracker.py's HTTPServer listens on port 8080)
const BASE_URL = 'http://localhost:8080';
const ACTIVE_TAB_URL = BASE_URL + '/active-tab';
const FOCUS_STATUS_URL = BASE_URL + '/focus-status';

async function sendUrlToTracker(url) {
    if (!url || url.startsWith('chrome://') || url.startsWith('chrome-extension://')) {
        return;
    }

    try {
        await fetch(ACTIVE_TAB_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url: url }),
        });
    } catch (error) {
        console.error('Tracker daemon offline or unreachable:', error.message);
    }
}

// --- Focus Session enforcement ------------------------------------------
// Separate from the daily-limit tracking above: when a Focus Session is
// running (started from the app's Focus tab), any tab whose domain isn't
// on the session's allowed list gets redirected to a local "blocked" page
// instead of being sent anywhere. The daemon can't reach into the browser
// itself, so this poll-and-redirect is how it enforces tabs.

function domainFromUrl(url) {
    try {
        let host = new URL(url).hostname.toLowerCase();
        if (host.startsWith('www.')) {
            host = host.slice(4);
        }
        return host;
    } catch (e) {
        return null;
    }
}

function isDomainAllowed(domain, allowedDomains) {
    if (!domain) return false;
    // A domain covers its own subdomains too: allowing "google.com" should
    // also cover "docs.google.com", "mail.google.com", "drive.google.com",
    // etc, since Google (and most large sites) spread their products across
    // many different subdomains rather than one. Exact-match-only would mean
    // allowing "google.com" leaves every other Google product blocked.
    return allowedDomains.some((allowed) => domain === allowed || domain.endsWith('.' + allowed));
}

async function getFocusStatus() {
    try {
        const resp = await fetch(FOCUS_STATUS_URL);
        if (!resp.ok) {
            console.warn('[Narrowgate] /focus-status returned', resp.status);
            return null;
        }
        return await resp.json();
    } catch (error) {
        // Daemon offline/unreachable -- fail open rather than blocking
        // everything just because the tracker isn't running.
        console.warn('[Narrowgate] /focus-status fetch failed:', error.message);
        return null;
    }
}

function buildBlockedPageUrl(domain, remainingSeconds) {
    // Must be a page bundled with the extension (chrome-extension://...),
    // NOT a data: URL -- Chrome blocks top-level navigation to data: URLs
    // (since Chrome 71) specifically to stop extensions/pages from using
    // that trick to redirect a tab to an arbitrary fake page. chrome.tabs
    // .update() to a data: URL fails silently (no console error, no thrown
    // exception), which is why this looked like nothing was happening at
    // all rather than an obvious error.
    const params = new URLSearchParams({
        domain: domain || '',
        remaining: String(remainingSeconds),
    });
    return chrome.runtime.getURL('blocked.html') + '?' + params.toString();
}

async function enforceFocusForTab(tab) {
    if (!tab || !tab.id || !tab.url) {
        console.log('[Narrowgate] enforceFocusForTab: skipped, no tab/id/url', tab);
        return;
    }
    if (tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://') || tab.url.startsWith('data:')) {
        return; // never touch internal pages, including our own blocked page -- not logged, this is routine
    }

    const status = await getFocusStatus();
    console.log('[Narrowgate] enforceFocusForTab:', tab.url, '-> status:', status);
    if (!status || !status.active) return;

    const domain = domainFromUrl(tab.url);
    const allowed = isDomainAllowed(domain, status.allowed_domains);
    console.log('[Narrowgate] domain:', domain, 'allowed:', allowed, 'allowedDomains:', status.allowed_domains);
    if (!allowed) {
        console.log('[Narrowgate] blocking tab', tab.id, domain);
        chrome.tabs.update(tab.id, { url: buildBlockedPageUrl(domain, status.remaining_seconds) });
    }
}

// Backstop: even if you don't touch any tab after starting a session (or
// switch away and back), re-check whatever tab is currently in front once
// a minute -- chrome.alarms is the MV3-safe way to do periodic work, since
// a plain setInterval can be dropped when the service worker is suspended.
const FOCUS_CHECK_ALARM = 'focus-status-check';
chrome.alarms.create(FOCUS_CHECK_ALARM, { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(async (alarm) => {
    if (alarm.name !== FOCUS_CHECK_ALARM) return;
    try {
        const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
        if (tab) enforceFocusForTab(tab);
    } catch (e) {
        console.error(e);
    }
});

// --- Tab/window listeners -------------------------------------------------

// 1. Listen for active tab switching
chrome.tabs.onActivated.addListener(async (activeInfo) => {
    try {
        const tab = await chrome.tabs.get(activeInfo.tabId);
        if (tab && tab.url) {
            sendUrlToTracker(tab.url);
            enforceFocusForTab(tab);
        }
    } catch (e) {
        console.error(e);
    }
});

// 2. Listen for URL changes inside the active tab
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (tab.active && (changeInfo.url || changeInfo.status === 'complete')) {
        if (tab.url) {
            sendUrlToTracker(tab.url);
            enforceFocusForTab(tab);
        }
    }
});

// 3. Listen for focus switching between browser windows (e.g. two Chrome
// windows open, or alt-tabbing back into a different Chrome window). Without
// this, moving focus to a window whose active tab hasn't changed never fires
// onActivated, so the tracked URL goes stale.
chrome.windows.onFocusChanged.addListener(async (windowId) => {
    if (windowId === chrome.windows.WINDOW_ID_NONE) {
        return;
    }
    try {
        const [tab] = await chrome.tabs.query({ active: true, windowId });
        if (tab && tab.url) {
            sendUrlToTracker(tab.url);
            enforceFocusForTab(tab);
        }
    } catch (e) {
        console.error(e);
    }
});
