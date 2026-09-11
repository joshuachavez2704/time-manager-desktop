// Reads ?domain=...&remaining=... from this page's own URL (set by
// background.js when it redirects a disallowed tab here) and renders a
// live countdown. A separate file rather than an inline <script> in
// blocked.html because Manifest V3's default extension-page CSP disallows
// inline scripts.
const params = new URLSearchParams(location.search);
document.getElementById('domain').textContent = params.get('domain') || 'This site';

let remaining = parseInt(params.get('remaining'), 10);
if (Number.isNaN(remaining)) remaining = 0;

const el = document.getElementById('remaining');
function render() {
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    el.textContent = remaining > 0
        ? ('Time left: ' + m + 'm ' + String(s).padStart(2, '0') + 's')
        : 'Session ending...';
}
render();
setInterval(() => {
    remaining = Math.max(0, remaining - 1);
    render();
}, 1000);
