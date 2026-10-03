/* ============================================================
   NovaBot Dashboard - front-end logic
   Settings ko form se utha kar /api par save karta hai,
   aur embed builder ka live preview banata hai.
   ============================================================ */

(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* ---------------- Toast ---------------- */

  function toast(msg) {
    var el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(window.__toastTimer);
    window.__toastTimer = setTimeout(function () { el.classList.remove("show"); }, 3200);
  }

  /* ---------------- Select population ---------------- */

  function populateSelects() {
    $all("select[data-populate]").forEach(function (sel) {
      var kind = sel.dataset.populate;
      var items = kind === "channels" ? (window.CHANNELS || [])
        : kind === "categories" ? (window.CATEGORIES || [])
        : (window.ROLES || []);
      var withPlaceholder = sel.dataset.placeholder !== "off";

      sel.innerHTML = "";
      if (withPlaceholder) {
        var none = document.createElement("option");
        none.value = "0";
        none.textContent = kind === "roles" ? "@ (none)" : "# (none)";
        sel.appendChild(none);
      }
      items.forEach(function (item) {
        var opt = document.createElement("option");
        opt.value = String(item.id);
        opt.textContent = (kind === "channels" ? "# " : kind === "roles" ? "@ " : "📁 ") + item.name;
        sel.appendChild(opt);
      });
    });
  }

  /* ---------------- Settings <-> form ---------------- */

  function applySettings(form, data) {
    if (!form || !data) return;
    $all("[name]", form).forEach(function (el) {
      if (!(el.name in data)) return;
      var val = data[el.name];
      if (el.type === "checkbox") {
        el.checked = !!val;
      } else if (el.tagName === "SELECT") {
        var v = String(val === null || val === undefined ? 0 : val);
        var exists = Array.prototype.some.call(el.options, function (o) { return o.value === v; });
        if (!exists && v !== "0") {
          // Channel/role delete ho chuka hai - id wipe karne se bachao
          var ghost = document.createElement("option");
          ghost.value = v;
          ghost.textContent = "(deleted / unknown ID " + v + ")";
          el.appendChild(ghost);
        }
        el.value = v;
      } else if (Array.isArray(val)) {
        el.value = val.join("\n");
      } else {
        el.value = val === null || val === undefined ? "" : String(val);
      }
    });
  }

  function collect(form) {
    var out = {};
    $all("[name]", form).forEach(function (el) {
      var key = el.name;
      if (el.type === "checkbox") out[key] = el.checked;
      else if (el.type === "number") out[key] = parseInt(el.value || "0", 10) || 0;
      else if (key === "whitelist") out[key] = el.value.split(/[\s,]+/).filter(Boolean);
      // Discord IDs 19-digit hote hain (> 2^53) - parseInt/Number se precision
      // chali jaati hai aur last digits chup-chaap badal jaate hain.
      // Isliye ID hamesha string ki tarah bhejo (settings.py int mein coerce kar leta hai).
      else if (key.slice(-3) === "_id") out[key] = String(el.value || "0").trim() || "0";
      // Welcome/verify/ticket text mein `:naam:` chipka ho to save karte waqt
      // hi asli emoji syntax bana do, warna bot bhejega to Discord text dikha dega
      else out[key] = resolveEmojiCodes(el.value);
    });
    return out;
  }

  /* ---------------- Save ---------------- */

  function saveSection(section) {
    var form = $('form[data-section="' + section + '"]');
    if (!form) return Promise.resolve();
    var data = collect(form);

    return fetch("/api/" + window.GUILD_ID + "/" + section, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": window.CSRF || "" },
      body: JSON.stringify(data)
    })
      .then(function (res) { return res.json().catch(function () { return {}; }); })
      .then(function (json) {
        if (json.ok) {
          window.SETTINGS = window.SETTINGS || {};
          window.SETTINGS[section] = json.saved;
          applySettings(form, json.saved);
          updateOverview();
          updateSectionPreview(section);
          toast("✅ " + section + " save ho gaya");
        } else {
          toast("❌ Save fail: " + (json.error || "unknown error"));
        }
      })
      .catch(function () { toast("❌ Network error - dashboard chal raha hai?"); });
  }

  /* ---------------- Dashboard se panel / test message bhejna ---------------- */

  var SEND_ACTIONS = {
    "welcome-test": { path: "/welcome/test", body: { kind: "welcome" } },
    "leave-test": { path: "/welcome/test", body: { kind: "leave" } },
    "verify-panel": { path: "/verification/panel", body: {} },
    "ticket-panel": { path: "/tickets/panel", body: {} }
  };

  function sendToDiscord(key) {
    var act = SEND_ACTIONS[key];
    if (!act) return;
    var btn = document.querySelector('[data-send="' + key + '"]');
    if (btn) { btn.disabled = true; btn.dataset.old = btn.textContent; btn.textContent = "⏳ Bhej raha hai..."; }

    fetch("/api/" + window.GUILD_ID + act.path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": window.CSRF || "" },
      body: JSON.stringify(act.body)
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (json) {
          if (btn) { btn.disabled = false; if (btn.dataset.old) btn.textContent = btn.dataset.old; }
          if (json.ok) toast("✅ Discord par bhej diya" + (json.channel ? "" : ""));
          else toast("❌ " + (json.error || "nahi bhej saka"));
        });
      })
      .catch(function () {
        if (btn) { btn.disabled = false; if (btn.dataset.old) btn.textContent = btn.dataset.old; }
        toast("❌ Network error - dashboard chal raha hai?");
      });
  }

  /* ---------------- Tabs ---------------- */

  function showTab(name) {
    closePicker();
    $all(".side-link").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.tab === name);
    });
    $all(".tab").forEach(function (sec) {
      sec.classList.toggle("hidden", sec.id !== "tab-" + name);
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /* ---------------- Overview status ---------------- */

  function updateOverview() {
    var s = window.SETTINGS || {};
    var sections = ["welcome", "verification", "tickets", "antinuke"];
    var count = 0;

    sections.forEach(function (key) {
      var on = !!(s[key] && s[key].enabled);
      if (on) count++;
      var badge = $('[data-module="' + key + '"]');
      if (badge) {
        badge.textContent = on ? "ON" : "OFF";
        badge.classList.toggle("badge-green", on);
        badge.classList.toggle("badge-grey", !on);
      }
    });

    var stat = $('[data-stat="modules"]');
    if (stat) stat.textContent = count;
  }

  /* ---------------- Embed builder ---------------- */

  function val(id) {
    var el = document.getElementById(id);
    return el ? String(el.value || "").trim() : "";
  }

  function updatePreview() {
    var title = val("emb-title");
    var desc = val("emb-desc");
    var color = val("emb-color") || "#5865f2";
    var image = val("emb-image");
    var thumb = val("emb-thumb");
    var footer = val("emb-footer");

    var t = document.getElementById("de-title");
    var d = document.getElementById("de-desc");
    var img = document.getElementById("de-image");
    var th = document.getElementById("de-thumb");
    var embedBox = document.getElementById("de-embed");
    var f = document.getElementById("de-footer");
    var bar = document.getElementById("de-bar");
    if (!t || !d) return;

    // title/footer = emoji + simple text, description = markdown + emoji (Discord jaisa)
    t.innerHTML = emojiHtml(title);
    t.hidden = !title;
    d.innerHTML = mdToHtml(desc);
    d.hidden = !desc;
    if (img) {
      if (image) { img.src = image; img.hidden = false; } else { img.hidden = true; img.removeAttribute("src"); }
    }
    if (th) {
      if (thumb) { th.src = thumb; th.hidden = false; } else { th.hidden = true; th.removeAttribute("src"); }
    }
    if (embedBox) embedBox.classList.toggle("has-thumb", !!thumb);
    if (f) { f.innerHTML = emojiHtml(footer); f.hidden = !footer; }
    if (bar) bar.style.background = color;
  }

  function sendEmbed() {
    var channel = $("#emb-channel") ? $("#emb-channel").value : "";
    if (!channel || channel === "0") { toast("❌ Pehle channel select karein"); return; }

    var embed = {};
    // Panel wale shortcodes (`:emoji_2~6:`) ko bhejne se pehle asli syntax mein badal do
    var title = resolveEmojiCodes(val("emb-title"));
    var desc = resolveEmojiCodes(val("emb-desc"));
    var color = val("emb-color");
    var image = val("emb-image");
    var thumb = val("emb-thumb");
    var footer = resolveEmojiCodes(val("emb-footer"));

    if (title) embed.title = title;
    if (desc) embed.description = desc;
    if (color) {
      var n = parseInt(color.replace("#", ""), 16);
      if (!isNaN(n)) embed.color = n;
    }
    if (image) embed.image = { url: image };
    if (thumb) embed.thumbnail = { url: thumb };
    if (footer) embed.footer = { text: footer };

    if (Object.keys(embed).length === 0) { toast("❌ Pehle kuch to likhein"); return; }

    fetch("/api/" + window.GUILD_ID + "/embed/send", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": window.CSRF || "" },
      body: JSON.stringify({ channel_id: channel, embed: embed })
    })
      .then(function (res) { return res.json().catch(function () { return {}; }); })
      .then(function (json) {
        if (json.ok) toast("📨 Embed Discord par bhej diya");
        else toast("❌ " + (json.error || "embed nahi gaya"));
      })
      .catch(function () { toast("❌ Network error"); });
  }

  /* ---------------- Live previews (Welcome / Verification / Tickets) ---------------- */

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* Chhota shortcode jaise `:naam:`, `:naam~2:` ya `:naam~2` -> asli Discord
     syntax (`<a:naam:id>` / `<:naam:id>`).

     Aise format kahin aur se copy karke yahan chipka diye jaate hain, aur
     Discord unhe plain text hi samajhta hai - isliye preview aur bhejne dono
     se pehle hum khud badal dete hain. Sirf tabhi badalta hai jab naam kisi
     asli emoji se match kare (warna "1:30" jaise normal text ko chhodega). */
  function resolveEmojiCodes(text) {
    var src = String(text == null ? "" : text);
    if (!src) return src;

    var map = {};
    emojiList().forEach(function (e) {
      if (e && e.name && e.id) map[String(e.name).toLowerCase()] = e;
    });
    if (!Object.keys(map).length) return src;

    // Pehla alternative = pehle se sahi syntax (`<a:naam:id>`) - use chhodna
    // hai, warna wo andar se dobara resolve hokar toot jayega. Group tabhi
    // bharta hai jab doosra (shortcode) wala branch match ho.
    return src.replace(
      /<a?:[a-zA-Z0-9_]{1,32}:\d{6,}>|:([a-zA-Z0-9_]{1,32})(?:~\d{1,4})?:?/g,
      function (m, name) {
        if (!name) return m;
        var e = map[name.toLowerCase()];
        if (!e) return m; // jaan-pehchan ka emoji nahi - jaisa hai waisa chhod do
        return (e.animated ? "<a:" : "<:") + e.name + ":" + e.id + ">";
      }
    );
  }

  /* Discord ka custom emoji syntax -> asli emoji image.
     `<a:naam:id>` = animated (gif), `<:naam:id>` = static (png).
     Input RAW text leta hai: pehle shortcodes resolve, phir escape, phir img. */
  function emojiHtml(text) {
    var escaped = escapeHtml(resolveEmojiCodes(text));
    return escaped.replace(
      /&lt;(a?):([a-zA-Z0-9_]{1,32}):(\d{6,})&gt;/g,
      function (m, anim, name, id) {
        var ext = anim === "a" ? "gif" : "png";
        return (
          '<img class="pv-emoji" alt=":' + name + ':" title=":' + name + ':" ' +
          'src="https://cdn.discordapp.com/emojis/' + id + "." + ext +
          '?size=48&amp;quality=lossless" />'
        );
      }
    );
  }

  /* Agar emoji delete ho gaya hai (404) to toota image na dikhe - text dikha do */
  document.addEventListener(
    "error",
    function (e) {
      var t = e.target;
      if (t && t.tagName === "IMG" && t.classList && t.classList.contains("pv-emoji") && t.parentNode) {
        t.parentNode.replaceChild(document.createTextNode(t.getAttribute("alt") || ""), t);
      }
    },
    true
  );

  /* Discord jaisa thoda sa markdown: `code`, **bold**, __underline__, *italic*
     (emoji pehle badal dete hain taaki markdown unhe na todo) */
  function mdToHtml(text) {
    var out = emojiHtml(text);
    out = out.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/__([^_\n]+)__/g, "<u>$1</u>");
    out = out.replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    return out.replace(/\n/g, "<br>");
  }

  /* Preview ke liye sample member - bot `_format` ke same variables use karta hai */
  function fillVars(text) {
    var vars = {
      "{user}": "@Alex",
      "{username}": "alex",
      "{display_name}": "Alex",
      "{server}": window.GUILD_NAME || "My Server",
      "{member_count}": "1,234",
      "{id}": "123456789012345678"
    };
    var out = String(text == null ? "" : text);
    Object.keys(vars).forEach(function (k) { out = out.split(k).join(vars[k]); });
    return out;
  }

  function colorOf(raw, fallback) {
    var bad = fallback || "#5865f2";
    var c = String(raw || "").trim();
    if (!c) return bad;
    if (c.charAt(0) !== "#") c = "#" + c;
    return /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(c) ? c : bad;
  }

  function sectionForm(section) {
    return $('form[data-section="' + section + '"]');
  }

  /* Form ke current values (live - jo user abhi type kar raha hai) */
  function formValues(section) {
    var form = sectionForm(section);
    var data = {};
    if (!form) return data;
    $all("[name]", form).forEach(function (el) {
      if (el.type === "checkbox") data[el.name] = el.checked;
      else if (el.type === "number") data[el.name] = parseInt(el.value || "0", 10) || 0;
      else data[el.name] = el.value;
    });
    return data;
  }

  function selectLabel(section, name) {
    var form = sectionForm(section);
    var sel = form ? form.querySelector('[name="' + name + '"]') : null;
    var opt = sel && sel.selectedOptions && sel.selectedOptions[0];
    if (!opt) return "";
    return opt.textContent.replace(/^[@#📁]\s*/, "").trim();
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  /* Ek Discord jaisa message block banao */
  function chatMessage(opts) {
    var row = el("div", "chat-row");

    var img = document.createElement("img");
    img.className = "avatar";
    img.alt = "";
    img.src = "https://cdn.discordapp.com/embed/avatars/0.png";
    row.appendChild(img);

    var content = el("div", "chat-content");

    var name = el("div", "chat-name");
    name.appendChild(document.createTextNode(opts.sender || "NovaBot"));
    name.appendChild(el("span", "bot-tag", "APP"));
    name.appendChild(el("span", "pv-time", opts.time || "Today at 12:00 PM"));
    content.appendChild(name);

    if (opts.text) {
      var tn = el("div", "pv-text");
      tn.innerHTML = mdToHtml(opts.text);
      content.appendChild(tn);
    }

    if (opts.embed) {
      var wrap = el("div", "discord-embed");
      wrap.appendChild(el("div", "de-bar")).style.background = opts.embed.color || "#5865f2";
      var body = el("div", "de-body");
      if (opts.embed.title) body.appendChild(htmlNode("de-title", emojiHtml(opts.embed.title)));
      if (opts.embed.desc) body.appendChild(nodeWithMd(opts.embed.desc));
      if (opts.embed.footer) body.appendChild(htmlNode("de-footer", emojiHtml(opts.embed.footer)));
      wrap.appendChild(body);
      content.appendChild(wrap);
    }

    if (opts.buttons && opts.buttons.length) {
      var bw = el("div", "pv-buttons");
      opts.buttons.forEach(function (b) {
        var btn = el("button", "pv-btn " + (b.style || "primary"), (b.emoji ? b.emoji + " " : "") + b.label);
        btn.type = "button";
        bw.appendChild(btn);
      });
      content.appendChild(bw);
    }

    row.appendChild(content);
    return row;
  }

  function htmlNode(cls, html) {
    var n = el("div", cls);
    n.innerHTML = html;
    return n;
  }

  function nodeWithMd(text) {
    return htmlNode("de-desc", mdToHtml(text));
  }

  function renderPreview(id, channelLabel, msgOpts) {
    var box = document.getElementById(id);
    if (!box) return;
    box.textContent = "";
    var ch = el("div", "pv-channel", channelLabel || "# general");
    box.appendChild(ch);
    box.appendChild(chatMessage(msgOpts));
  }

  function setNote(id, text) {
    var n = document.getElementById(id);
    if (n) n.textContent = text;
  }

  function setCtx(id, text) {
    var n = document.getElementById(id);
    if (n) n.textContent = text || "";
  }

  function onOff(v) { return v ? "ON" : "OFF"; }

  function updateWelcomePreview() {
    var v = formValues("welcome");
    var msg = fillVars(v.message);
    var useEmbed = !!v.use_embed;

    renderPreview("pv-welcome", "# " + (selectLabel("welcome", "channel_id") || "(channel select karein)"), {
      text: useEmbed ? null : (msg || "(koi message nahi)"),
      embed: useEmbed ? { title: "Welcome Alex!", desc: msg, color: colorOf(v.embed_color, "#57f287") } : null
    });

    renderPreview("pv-dm", "📩 Direct Message", { text: fillVars(v.dm_message) || "(DM message khaali hai)" });

    renderPreview("pv-leave", "# " + (selectLabel("welcome", "leave_channel_id") || "(channel select karein)"), {
      text: fillVars(v.leave_message) || "(leave message khaali hai)"
    });

    setNote(
      "pv-welcome-note",
      "Welcome: " + onOff(v.enabled) + " · Join DM: " + onOff(v.dm_enabled) +
      " · Leave: " + onOff(v.leave_enabled) + " — Save dabate hi lagu ho jayega."
    );
  }

  function updateVerificationPreview() {
    var v = formValues("verification");
    var chan = selectLabel("verification", "channel_id");
    var role = selectLabel("verification", "role_id");

    setCtx("pv-verify-ctx", "· " + (chan ? "#" + chan : "channel select karein") +
      (role ? " · milega role: @" + role : ""));

    renderPreview("pv-verification", "# " + (chan || "(channel select karein)"), {
      embed: {
        title: "🛡️ Verification",
        desc: fillVars(v.message) || "Click the button below to verify.",
        color: colorOf(v.embed_color),
        footer: "Neeche diya gaya button dabayein"
      },
      buttons: [{ label: "Verify", emoji: "✅", style: "primary" }]
    });

    setNote(
      "pv-verification-note",
      "Verification: " + onOff(v.enabled) +
      (role ? "" : " · ⚠️ Verify role select nahi kiya") +
      " — panel bhejne ke liye /verify panel chalayein."
    );
  }

  function updateTicketsPreview() {
    var v = formValues("tickets");
    var chan = selectLabel("tickets", "panel_channel_id");
    var support = selectLabel("tickets", "support_role_id");
    var cat = selectLabel("tickets", "category_id");

    setCtx(
      "pv-ticket-ctx",
      "· " + (chan ? "#" + chan : "channel select karein") +
      (support ? " · support: @" + support : "") +
      (cat ? " · 📁 " + cat : "")
    );

    renderPreview("pv-tickets", "# " + (chan || "(channel select karein)"), {
      embed: {
        title: "🎫 Support Tickets",
        desc: fillVars(v.message) || "Need help? Open a ticket below.",
        color: colorOf(v.embed_color),
        footer: "Ek waqt mein ek hi ticket khuli ho sakti hai"
      },
      buttons: [{ label: "Open Ticket", emoji: "🎫", style: "primary" }]
    });

    setNote(
      "pv-tickets-note",
      "Tickets: " + onOff(v.enabled) +
      (support ? "" : " · ⚠️ Support role select nahi kiya") +
      " — panel bhejne ke liye /ticket panel chalayein."
    );
  }

  var PREVIEWS = {
    welcome: updateWelcomePreview,
    verification: updateVerificationPreview,
    tickets: updateTicketsPreview
  };

  function updateSectionPreview(section) {
    if (PREVIEWS[section]) PREVIEWS[section]();
  }

  /* ---------------- Color swatch <-> hex box ---------------- */

  function initColorSwatches() {
    $all(".color-swatch[data-swatch]").forEach(function (sw) {
      var form = sw.closest("form");
      var hex = form ? form.querySelector('[name="' + sw.dataset.swatch + '"]') : null;
      if (!hex) return;

      // text box se swatch (page load / save ke baad)
      var syncFromText = function () {
        var v = String(hex.value || "").trim();
        if (v && v.charAt(0) !== "#") v = "#" + v;
        if (/^#[0-9a-fA-F]{6}$/.test(v)) sw.value = v.toLowerCase();
      };
      syncFromText();
      hex.addEventListener("input", syncFromText);

      // swatch se text box (live preview ko foran chahiye isliye input event bhi)
      sw.addEventListener("input", function () {
        hex.value = sw.value;
        hex.dispatchEvent(new Event("input", { bubbles: true }));
      });
    });
  }

  /* ---------------- Emoji picker (server ke custom + animated emojis) ---------------- */

  var pickerEl = null;
  var pickerTarget = null;

  function emojiList() {
    var list = window.EMOJIS;
    return Array.isArray(list) ? list : [];
  }

  /* Discord ka asli syntax - yahi message/embed mein jaata hai */
  function emojiSyntax(e) {
    return (e.animated ? "<a:" : "<:") + e.name + ":" + e.id + ">";
  }

  function emojiCdn(e) {
    return (
      "https://cdn.discordapp.com/emojis/" + e.id + "." + (e.animated ? "gif" : "png") +
      "?size=48&quality=lossless"
    );
  }

  /* Cursor ki jagah par text daalo (na ke end par) */
  function insertAtCursor(input, text) {
    var val = String(input.value == null ? "" : input.value);
    var start = typeof input.selectionStart === "number" ? input.selectionStart : null;
    if (start === null) {
      input.value = val + text;
      return;
    }
    var end = typeof input.selectionEnd === "number" ? input.selectionEnd : start;
    input.value = val.slice(0, start) + text + val.slice(end);
    try { input.setSelectionRange(start + text.length, start + text.length); } catch (e) { /* ignore */ }
  }

  function closePicker() {
    if (pickerEl) pickerEl.classList.add("hidden");
    pickerTarget = null;
  }

  function buildPicker() {
    if (pickerEl) return pickerEl;
    pickerEl = document.createElement("div");
    pickerEl.id = "emoji-picker";
    pickerEl.className = "emoji-picker hidden";
    document.body.appendChild(pickerEl);
    return pickerEl;
  }

  function renderPicker() {
    var p = buildPicker();
    p.innerHTML = "";

    var list = emojiList();
    p.appendChild(
      el(
        "div",
        "emoji-head",
        list.length
          ? "Server ke emojis (" + list.length + ") - click karne par text mein lag jayega"
          : "Is server mein koi custom emoji nahi hai"
      )
    );
    if (!list.length) return;

    var grid = el("div", "emoji-grid");
    list.forEach(function (e) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "emoji-item";
      b.title = ":" + e.name + ":" + (e.animated ? " (animated)" : "");
      var img = document.createElement("img");
      img.src = emojiCdn(e);
      img.alt = ":" + e.name + ":";
      b.appendChild(img);
      b.addEventListener("click", function () {
        if (!pickerTarget) return;
        insertAtCursor(pickerTarget, emojiSyntax(e));
        // live preview foran update ho jaye
        pickerTarget.dispatchEvent(new Event("input", { bubbles: true }));
        toast("😀 :" + e.name + ": lag gaya");
      });
      grid.appendChild(b);
    });
    p.appendChild(grid);
  }

  function openPicker(btn, target) {
    var p = buildPicker();
    pickerTarget = target;
    renderPicker();
    p.classList.remove("hidden");

    // button ke neeche, jagah na ho to upar
    var r = btn.getBoundingClientRect();
    var ph = p.offsetHeight;
    var left = Math.min(Math.max(8, r.left), Math.max(8, window.innerWidth - p.offsetWidth - 8));
    var top = r.bottom + 6;
    if (top + ph > window.innerHeight - 8 && r.top - ph - 6 > 0) top = r.top - ph - 6;
    p.style.left = left + "px";
    p.style.top = top + "px";
  }

  function toggleEmojiPicker(btn, target) {
    if (pickerEl && !pickerEl.classList.contains("hidden") && pickerTarget === target) {
      closePicker();
      return;
    }
    openPicker(btn, target);
  }

  /* Har [data-emoji] field ke label mein "😀 Emoji" button jod do */
  function initEmojiPickers() {
    $all("[data-emoji]").forEach(function (target) {
      var field = target.closest ? target.closest(".field") : null;
      var label = field ? field.querySelector("label") : null;
      if (!label) return;

      label.classList.add("label-emoji");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "emoji-trigger";
      btn.textContent = "😀 Emoji";
      btn.title = "Server ke custom + animated emoji lagayein";
      btn.addEventListener("click", function () { toggleEmojiPicker(btn, target); });
      label.appendChild(btn);
    });

    document.addEventListener("click", function (e) {
      if (!pickerEl || pickerEl.classList.contains("hidden")) return;
      if (pickerEl.contains(e.target)) return;
      if (e.target && e.target.closest && e.target.closest(".emoji-trigger")) return;
      closePicker();
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closePicker(); });
    window.addEventListener("scroll", closePicker, true);
  }

  /* ---------------- Init ---------------- */

  window.initDashboard = function () {
    populateSelects();
    initEmojiPickers();

    $all("form[data-section]").forEach(function (form) {
      form.addEventListener("submit", function (e) { e.preventDefault(); });
      applySettings(form, (window.SETTINGS || {})[form.dataset.section]);
    });

    updateOverview();

    // Dashboard se seedha Discord par panel / test message bhejne wale buttons
    $all("[data-send]").forEach(function (btn) {
      btn.addEventListener("click", function () { sendToDiscord(btn.dataset.send); });
    });

    // Live previews - form mein kuch bhi badlo to foran update
    initColorSwatches();
    Object.keys(PREVIEWS).forEach(function (section) {
      var form = sectionForm(section);
      if (!form) return;
      ["input", "change"].forEach(function (evt) {
        form.addEventListener(evt, function () { updateSectionPreview(section); });
      });
      updateSectionPreview(section);
    });

    $all("[data-tab]").forEach(function (btn) {
      btn.addEventListener("click", function () { showTab(btn.dataset.tab); });
    });

    $all("[data-save]").forEach(function (btn) {
      btn.addEventListener("click", function () { saveSection(btn.dataset.save); });
    });

    var saveAll = document.getElementById("save-all");
    if (saveAll) {
      saveAll.addEventListener("click", function () {
        var sections = $all("form[data-section]").map(function (f) { return f.dataset.section; });
        Promise.all(sections.map(saveSection)).then(function () { toast("💾 Sab sections save ho gaye"); });
      });
    }

    ["emb-title", "emb-desc", "emb-color", "emb-image", "emb-thumb", "emb-footer"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("input", updatePreview);
    });

    var sendBtn = document.getElementById("emb-send");
    if (sendBtn) sendBtn.addEventListener("click", sendEmbed);

    updatePreview();
  };

  /* Landing / server pages ke liye chhota toast helper */
  window.showToast = toast;
})();
