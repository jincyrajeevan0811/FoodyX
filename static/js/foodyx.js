/* FoodyX shared UI behaviour */
(function () {
  "use strict";

  // ---- theme (saved per browser)
  function getTheme() {
    try { return localStorage.getItem("fx-theme") || "light"; } catch (e) { return "light"; }
  }
  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("fx-theme", t); } catch (e) { /* ignore */ }
  }
  setTheme(getTheme());

  window.FX = window.FX || {};
  FX.icons = function () { if (window.lucide) { window.lucide.createIcons(); } };
  FX.money = function (n) {
    n = Number(n || 0);
    var whole = Math.round(n * 100) / 100;
    return "₹" + whole.toLocaleString("en-IN", { minimumFractionDigits: whole % 1 ? 2 : 0, maximumFractionDigits: 2 });
  };
  FX.csrf = function () {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    if (m) return m[1];
    var el = document.querySelector("input[name=csrfmiddlewaretoken]");
    return el ? el.value : "";
  };
  // Poll a URL and swap the HTML of a container (used by live orders & kitchen)
  FX.poll = function (url, target, ms, onSwap) {
    var el = document.querySelector(target);
    if (!el) return;
    setInterval(function () {
      if (document.hidden) return;
      fetch(url, { headers: { "x-requested-with": "fetch" }, credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (html) {
          if (html === null) return;
          el.innerHTML = html;
          FX.icons();
          if (onSwap) onSwap(el);
        })
        .catch(function () { /* offline: keep showing the last data */ });
    }, ms || 10000);
  };
  FX.beep = function () {
    try {
      var ctx = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.18].forEach(function (t) {
        var o = ctx.createOscillator(), g = ctx.createGain();
        o.type = "sine"; o.frequency.value = 880;
        g.gain.setValueAtTime(0.0001, ctx.currentTime + t);
        g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + t + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + t + 0.15);
        o.connect(g); g.connect(ctx.destination); o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.16);
      });
    } catch (e) { /* audio not allowed yet */ }
  };

  document.addEventListener("DOMContentLoaded", function () {
    FX.icons();

    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      b.addEventListener("click", function () {
        setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
      });
    });

    var menuBtn = document.querySelector("[data-menu-toggle]");
    if (menuBtn) {
      menuBtn.addEventListener("click", function () { document.body.classList.toggle("nav-open"); });
      document.addEventListener("click", function (e) {
        if (document.body.classList.contains("nav-open") && !e.target.closest(".sidebar") && !e.target.closest("[data-menu-toggle]")) {
          document.body.classList.remove("nav-open");
        }
      });
    }

    // dropdowns
    document.querySelectorAll("[data-dropdown]").forEach(function (dd) {
      var trigger = dd.querySelector("[data-dropdown-trigger]");
      if (!trigger) return;
      trigger.addEventListener("click", function (e) { e.stopPropagation(); dd.classList.toggle("open"); });
    });
    document.addEventListener("click", function (e) {
      document.querySelectorAll("[data-dropdown].open").forEach(function (dd) {
        if (!dd.contains(e.target)) dd.classList.remove("open");
      });
      document.querySelectorAll("details.tile-menu[open]").forEach(function (d) {
        if (!d.contains(e.target)) d.removeAttribute("open");
      });
    });

    // toasts
    document.querySelectorAll(".toast").forEach(function (t, i) {
      var close = function () { t.style.transition = "opacity .3s, transform .3s"; t.style.opacity = 0; t.style.transform = "translateY(-6px)"; setTimeout(function () { t.remove(); }, 320); };
      var x = t.querySelector(".x");
      if (x) x.addEventListener("click", close);
      setTimeout(close, 5200 + i * 600);
    });

    // modals: <button data-open="dialogId">
    document.addEventListener("click", function (e) {
      var opener = e.target.closest("[data-open]");
      if (opener) {
        var d = document.getElementById(opener.getAttribute("data-open"));
        if (d && d.showModal) { e.preventDefault(); d.showModal(); }
      }
      var closer = e.target.closest("[data-close]");
      if (closer) {
        var dlg = closer.closest("dialog");
        if (dlg) { e.preventDefault(); dlg.close(); }
      }
    });
    document.querySelectorAll("dialog.modal").forEach(function (d) {
      d.addEventListener("click", function (e) { if (e.target === d) d.close(); });
    });

    // confirmations: <form data-confirm="Are you sure?">
    document.addEventListener("submit", function (e) {
      var msg = e.target.getAttribute("data-confirm");
      if (msg && !window.confirm(msg)) { e.preventDefault(); }
    });

    // select-all checkboxes: <input type=checkbox data-check-all=".row-check">
    document.querySelectorAll("[data-check-all]").forEach(function (box) {
      box.addEventListener("change", function () {
        document.querySelectorAll(box.getAttribute("data-check-all")).forEach(function (c) {
          if (c.closest("tr") && c.closest("tr").style.display === "none") return;
          c.checked = box.checked;
        });
      });
    });

    // auto-submit selects: <select data-autosubmit>
    document.querySelectorAll("[data-autosubmit]").forEach(function (s) {
      s.addEventListener("change", function () { s.form.submit(); });
    });

    // copy buttons: <button data-copy="text">
    document.querySelectorAll("[data-copy]").forEach(function (b) {
      b.addEventListener("click", function () {
        var text = b.getAttribute("data-copy");
        if (navigator.clipboard) {
          navigator.clipboard.writeText(text).then(function () {
            var old = b.innerHTML; b.textContent = "Copied!"; setTimeout(function () { b.innerHTML = old; FX.icons(); }, 1400);
          });
        }
      });
    });

    // active sidebar link
    var path = window.location.pathname;
    var best = null;
    document.querySelectorAll(".side-link[href]").forEach(function (a) {
      var href = a.getAttribute("href");
      if (path === href || (href.length > 1 && path.indexOf(href) === 0)) {
        if (!best || href.length > best.getAttribute("href").length) best = a;
      }
    });
    if (best) best.classList.add("active");
  });
})();
