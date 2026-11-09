/* NEXUS landing: theme toggle + waitlist form. No third-party code, no tracking. */
(function () {
  var root = document.documentElement;
  var KEY = "nexus-theme";
  function get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function set(v) { try { if (v) localStorage.setItem(KEY, v); else localStorage.removeItem(KEY); } catch (e) {} }
  var saved = get();
  if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme");
    if (btn) {
      var labels = { auto: btn.dataset.auto, light: btn.dataset.light, dark: btn.dataset.dark };
      var paint = function () {
        var m = root.getAttribute("data-theme") || "auto";
        btn.textContent = labels[m];
        btn.setAttribute("aria-label", btn.dataset.aria + ": " + labels[m]);
      };
      btn.addEventListener("click", function () {
        var m = root.getAttribute("data-theme") || "auto";
        var next = m === "auto" ? "light" : m === "light" ? "dark" : "auto";
        if (next === "auto") { root.removeAttribute("data-theme"); set(null); }
        else { root.setAttribute("data-theme", next); set(next); }
        paint();
      });
      paint();
    }

    var form = document.getElementById("waitlist");
    if (!form) return;
    var email = form.elements.email, role = form.elements.role, consent = form.elements.consent;
    var msg = document.getElementById("form-msg");
    var T = form.dataset;
    var re = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
    function fail(el, id, text) {
      el.setAttribute("aria-invalid", "true");
      document.getElementById(id).textContent = text;
    }
    function clear() {
      [email, role, consent].forEach(function (el) { el.removeAttribute("aria-invalid"); });
      ["err-email", "err-role", "err-consent"].forEach(function (i) { document.getElementById(i).textContent = ""; });
      msg.hidden = true; msg.className = "form-msg";
    }
    function show(kind, text) { msg.hidden = false; msg.className = "form-msg " + kind; msg.textContent = text; }

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      clear();
      var bad = null;
      if (!re.test(email.value.trim())) { fail(email, "err-email", T.errEmail); bad = bad || email; }
      if (!role.value) { fail(role, "err-role", T.errRole); bad = bad || role; }
      if (!consent.checked) { fail(consent, "err-consent", T.errConsent); bad = bad || consent; }
      if (bad) { bad.focus(); return; }
      if (form.elements.website.value) return; // honeypot
      var endpoint = (form.dataset.endpoint || "").trim();
      if (!endpoint) { show("demo", T.msgDemo); return; }
      var btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ email: email.value.trim(), role: role.value, lang: root.lang, source: "landing" })
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        form.reset(); show("ok", T.msgOk);
      }).catch(function () { show("bad", T.msgErr); })
        .then(function () { btn.disabled = false; });
    });
  });
})();
