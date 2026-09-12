// ===========================================================================
// subscribe.js — the mailing-list form, shared by every page (owen,
// 2026-08-18).
//
// WHY THIS EXISTS: the site had no working call to action anywhere. Every
// page carried "Coming soon to the App Store" as an <a> with no href, so a
// visitor who had just watched a champion's replay and wanted the game had
// literally nothing to click. The store button stays honest until release
// (see the itunes lookup in each page's head); this is what fills the gap in
// the meantime, and it keeps its value afterwards for season results.
//
// WHY IT IS ONE SCRIPT AND NOT MARKUP IN FOUR PAGES: the form has a live
// endpoint, validation, three visual states and a privacy line. Copied into
// four static pages it would be four things to keep in step, and the one that
// drifts is the one nobody reloads. Drop <div class="subscribe-mount"></div>
// where it should appear and include this file.
//
// It renders NOTHING if the mount is absent, so including it everywhere is
// safe.
// ===========================================================================
(function () {
  "use strict";

  // ⚠ THE API IS A DIFFERENT ORIGIN, so this only works because
  // /v1/subscribers is on a CORS allow-list server-side. If a new page is
  // served from a host that is not on that list the browser will refuse the
  // reply and the form will report a network error — the fix is the server's
  // allow-list, not a wildcard here.
  var LOCAL = /^(localhost|127\.0\.0\.1)$/.test(location.hostname);
  var API = LOCAL
    ? "http://localhost:5099"
    : "https://rb-api-902243335343.us-central1.run.app";

  var CSS = [
    ".subscribe{border:1px solid #2a2f3c;border-radius:14px;padding:22px 22px 18px;",
    "  background:linear-gradient(180deg,#161a22,#12151c);margin:34px 0}",
    ".subscribe h2{margin:0 0 6px;font-size:1.25rem;letter-spacing:-.01em}",
    ".subscribe .sub-lede{margin:0 0 16px;color:#9aa4b4;font-size:.94rem;line-height:1.5;max-width:52ch}",
    ".subscribe form{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start}",
    ".subscribe input[type=email]{flex:1 1 260px;min-width:0;background:#0e1117;color:#e9edf3;",
    /* A 2px border, not a lighter fill. Measured on the ARENA dock: any fill
       dark enough to read white text on cannot reach 3:1 against a dark
       panel, and the border can. Same fix, same reason. */
    "  border:2px solid #6B7080;border-radius:9px;padding:12px 13px;font:inherit;font-size:1rem}",
    ".subscribe input[type=email]:focus{outline:none;border-color:#8ea2ff}",
    ".subscribe button{background:#3358f4;color:#fff;border:0;border-radius:9px;padding:12px 20px;",
    "  font:inherit;font-weight:700;font-size:1rem;cursor:pointer;min-height:46px}",
    ".subscribe button:hover{background:#2b4bd8}",
    ".subscribe button[disabled]{opacity:.6;cursor:default}",
    ".subscribe .opts{display:flex;flex-wrap:wrap;gap:16px;margin:14px 0 0}",
    ".subscribe .opts label{display:flex;align-items:center;gap:8px;color:#c3cbd9;font-size:.9rem;cursor:pointer}",
    ".subscribe .opts input{width:17px;height:17px;accent-color:#3358f4}",
    ".subscribe .fine{margin:14px 0 0;color:#7f8797;font-size:.78rem;line-height:1.5}",
    ".subscribe .fine a{color:#9aa4b4}",
    ".subscribe .msg{margin:12px 0 0;font-size:.9rem;line-height:1.5}",
    ".subscribe .msg.err{color:#ffb4a8}",
    ".subscribe .done{display:flex;gap:12px;align-items:flex-start}",
    ".subscribe .done .tick{color:#5fd08a;font-size:1.4rem;line-height:1}",
    ".subscribe .done p{margin:0;color:#c3cbd9;line-height:1.55}",
    ".subscribe .done b{color:#e9edf3}",
    /* Off-screen rather than display:none — a bot that skips hidden fields is
       the point, and some skip anything undisplayed. */
    ".subscribe .hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}",
    "@media (max-width:520px){.subscribe form{flex-direction:column}",
    /* ⚠ flex-basis IS ON THE MAIN AXIS, AND THE MAIN AXIS JUST FLIPPED. The
       input is `flex:1 1 260px` so it can sit beside the button on a wide
       screen; the moment this query makes the form a COLUMN, that 260px
       becomes a 260px HEIGHT. Measured at 390px: a 260px-tall email box —
       on the only working call to action the site has. width:100% does not
       touch it. */
    "  .subscribe input[type=email]{flex:0 0 auto}",
    "  .subscribe input[type=email],.subscribe button{width:100%}}"
  ].join("");

  function styles() {
    if (document.getElementById("subscribe-css")) return;
    var s = document.createElement("style");
    s.id = "subscribe-css";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function render(mount) {
    var source = mount.getAttribute("data-source") || (location.pathname.replace(/\/+$/, "") || "/home");
    mount.className = "subscribe";
    mount.innerHTML =
      '<h2>Get game &amp; season news</h2>' +
      '<p class="sub-lede">Robot Brawl is out now - play it ' +
      '<a href="/play/rb/">free in your browser</a> or get it on the ' +
      '<a href="https://apps.apple.com/app/id6801680303" rel="noopener">App Store</a>. Leave your ' +
      'email for game updates — and, if you want it, who took each ' +
      'weight class at the end of every season.</p>' +
      '<form novalidate>' +
        '<input type="email" name="email" placeholder="you@example.com" autocomplete="email" ' +
               'aria-label="Your email address" required>' +
        '<button type="submit">Notify me</button>' +
        '<div class="hp" aria-hidden="true">' +
          '<label>Leave this empty<input type="text" name="website" tabindex="-1" autocomplete="off"></label>' +
        '</div>' +
      '</form>' +
      '<div class="opts">' +
        '<label><input type="checkbox" name="updates" checked> Game updates</label>' +
        '<label><input type="checkbox" name="seasons" checked> Season results &amp; champions</label>' +
      '</div>' +
      '<p class="msg" role="status" aria-live="polite"></p>' +
      // ⚠ THIS PROMISE HAS TO MATCH WHAT WE CAN ACTUALLY DO. It used to say
      // "unsubscribe in one click", which needs a per-recipient link in every
      // email. Updates are sent BY HAND for now — one message BCC'd to
      // everyone, so one body and one link for all of them. The honest
      // sentence is a link to a page you type your address into, and that is
      // what /unsubscribe/ is. Restore the stronger wording if a real send
      // pipeline ever puts a token in each message.
      '<p class="fine">Only when there is real news — a game update or a season ending. No ads, no tracking, ' +
      'no sharing your address with anyone. Every email links to ' +
      '<a href="/unsubscribe/">one-step unsubscribe</a>. ' +
      'See our <a href="/privacy/">privacy policy</a>.</p>';

    var form = mount.querySelector("form");
    var email = mount.querySelector('input[name=email]');
    var hp = mount.querySelector('input[name=website]');
    var btn = mount.querySelector("button");
    var msg = mount.querySelector(".msg");
    var updates = mount.querySelector('input[name=updates]');
    var seasons = mount.querySelector('input[name=seasons]');

    function say(text, isErr) {
      msg.textContent = text;
      msg.className = "msg" + (isErr ? " err" : "");
    }

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var addr = (email.value || "").trim();
      // Same rule as the server, deliberately loose: address grammar is not a
      // regex and every clever pattern rejects somebody's real address.
      if (addr.length < 3 || addr.indexOf("@") < 0 || /\s/.test(addr)) {
        say("That does not look like an email address.", true);
        email.focus();
        return;
      }
      if (!updates.checked && !seasons.checked) {
        say("Pick at least one thing to hear about.", true);
        return;
      }
      // The honeypot: a real person never fills a field they cannot see. Show
      // them success rather than an error — telling a bot it was caught is
      // telling it what to change.
      if (hp.value) { done(addr); return; }

      btn.disabled = true;
      say("Signing you up…", false);

      fetch(API + "/v1/subscribers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: addr,
          updates: updates.checked,
          seasons: seasons.checked,
          source: source
        })
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (body) {
          return { ok: r.ok, status: r.status, body: body };
        });
      }).then(function (res) {
        if (res.ok) { done(addr); return; }
        btn.disabled = false;
        if (res.status === 429) {
          say("That is a lot of signups from your network just now — try again in a minute.", true);
        } else {
          say(res.body && res.body.error
            ? res.body.error
            : "Something went wrong signing you up. Please try again.", true);
        }
      }).catch(function () {
        btn.disabled = false;
        // Be honest about what we do not know. The address was not saved, and
        // saying "you're on the list" here would be a lie that costs a signup.
        say("Could not reach the server. Please check your connection and try again.", true);
      });
    });

    function done(addr) {
      mount.innerHTML =
        '<div class="done"><span class="tick" aria-hidden="true">✓</span>' +
        '<p><b>You are on the list.</b><br>We will email <b>' + esc(addr) + '</b> the day ' +
        'Robot Brawl goes live. Nothing else until then.</p></div>';
    }
  }

  // ⚠ THE HERO FORMS ARE STATIC MARKUP, ON PURPOSE. The signup block below is
  // built at runtime, which means none of its copy exists in the served HTML —
  // invisible to crawlers and to link-preview bots, and a silent no-CTA for
  // anyone whose JavaScript fails. The hero copy is the copy that matters
  // most, so it ships in the page and this only ATTACHES BEHAVIOUR to it.
  // (Submission still needs fetch: the API is another origin and answers
  // JSON, so there is no meaningful no-JS POST target. What static markup
  // buys is that the offer is always visible and always indexable.)
  function wireStatic(form) {
    var mount = form.closest(".herocta") || form.parentNode;
    var email = form.querySelector('input[name=email]');
    var btn = form.querySelector("button");
    var msg = mount.querySelector(".msg");
    var source = form.getAttribute("data-source") || "hero";
    function say(t, err) { if (msg) { msg.textContent = t; msg.className = "msg" + (err ? " err" : ""); } }
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var addr = (email.value || "").trim();
      if (addr.length < 3 || addr.indexOf("@") < 0 || /\s/.test(addr)) {
        say("That does not look like an email address.", true); email.focus(); return;
      }
      btn.disabled = true; say("Signing you up…", false);
      post(addr, true, true, source).then(function (res) {
        if (res.ok) {
          form.style.display = "none";
          msg.innerHTML = '<span class="ok">You are on the list.</span> We will email ' +
            esc(addr) + ' the day Robot Brawl goes live.';
          msg.className = "msg";
          return;
        }
        btn.disabled = false;
        say(res.status === 429
          ? "That is a lot of signups from your network just now — try again in a minute."
          : ((res.body && res.body.error) || "Something went wrong. Please try again."), true);
      }).catch(function () {
        btn.disabled = false;
        say("Could not reach the server. Please check your connection and try again.", true);
      });
    });
  }

  // One request path for both forms, so a fix to either is a fix to both.
  function post(addr, updates, seasons, source) {
    return fetch(API + "/v1/subscribers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: addr, updates: updates, seasons: seasons, source: source })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        return { ok: r.ok, status: r.status, body: body };
      });
    });
  }

  function boot() {
    var statics = document.querySelectorAll("form[data-subscribe]");
    Array.prototype.forEach.call(statics, wireStatic);
    var mounts = document.querySelectorAll(".subscribe-mount");
    if (!mounts.length) return;
    styles();
    Array.prototype.forEach.call(mounts, render);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
