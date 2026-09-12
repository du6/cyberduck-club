// ===========================================================================
// promo.js — the promo video block, shared by every page that wants one.
//
// The markup is written into the page by hand (so the poster and the <video>
// exist without JavaScript, and a crawler sees them). This file does the two
// things markup cannot:
//
//   1. CHOOSE THE RIGHT FILE. A <source media="..."> is honoured by exactly
//      nobody for <video> — browsers pick the first playable source and ignore
//      the media query — so a phone would pull the 10 MB 1080p file to play it
//      in a 360px box. This picks before anything is fetched, which is free
//      because the element is preload="none".
//   2. HONOUR SAVE-DATA. Someone on a metered connection who has asked their
//      browser to economise should not be handed 10 MB by a marketing page.
//
// It also keeps the poster showing until play is pressed: with preload="none"
// no video bytes move until then, so the page stays light for the majority of
// visitors who never press it.
// ===========================================================================
(function () {
  "use strict";

  function pick(v) {
    var small = window.matchMedia && window.matchMedia("(max-width: 900px)").matches;
    var conn = navigator.connection || {};
    var thrifty = conn.saveData === true ||
                  /^(slow-)?2g$/.test(conn.effectiveType || "");
    var want = (small || thrifty) ? v.getAttribute("data-src-720")
                                  : v.getAttribute("data-src-1080");
    if (!want) return;
    // Only touch the DOM if the choice differs from what is already there —
    // reassigning src on a <video> resets it, and doing that after someone has
    // pressed play would restart the film under them.
    var cur = v.querySelector("source");
    if (cur && cur.getAttribute("src") !== want && v.paused && !v.currentTime) {
      cur.setAttribute("src", want);
      v.load();
    }
  }

  function boot() {
    var vids = document.querySelectorAll("video.promo");
    Array.prototype.forEach.call(vids, function (v) {
      pick(v);
      // A viewer who plays the film has said what they came for; pause any
      // other video on the page rather than letting two run at once.
      v.addEventListener("play", function () {
        Array.prototype.forEach.call(vids, function (o) { if (o !== v) o.pause(); });
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
