/* Studio 1810c control surface - UI logic.
   State lives in the daemon; this file renders it and writes changes back. */

const PAIR_NAMES = ["Main", "Line 1/2", "Line 3/4", "S/PDIF", "Out 4", "Out 5", "Out 6", "Out 7", "Out 8"];
const VISIBLE_PAIRS = 4;

/* dB <-> fader travel. Piecewise so the useful range gets the travel. */
const CURVE = [[0, -96], [0.15, -60], [0.35, -30], [0.6, -12], [0.85, 0], [1, 10]];

function dbFromPos(pos) {
  pos = Math.min(1, Math.max(0, pos));
  for (let i = 1; i < CURVE.length; i++) {
    const [p1, d1] = CURVE[i];
    const [p0, d0] = CURVE[i - 1];
    if (pos <= p1) return d0 + (d1 - d0) * ((pos - p0) / (p1 - p0));
  }
  return CURVE[CURVE.length - 1][1];
}
function posFromDb(db) {
  db = Math.min(10, Math.max(-96, db));
  for (let i = 1; i < CURVE.length; i++) {
    const [p1, d1] = CURVE[i];
    const [p0, d0] = CURVE[i - 1];
    if (db <= d1) return p0 + (p1 - p0) * ((db - d0) / (d1 - d0));
  }
  return 0;
}
const fmtDb = (db) => (db <= -95.9 ? "-∞" : (db > 0 ? "+" : "") + db.toFixed(1));

const state = {
  info: null,
  pair: 0,
  strips: {},     // "pair:ch" -> {level_db, pan, mute}
  outputs: {},    // "pair" -> {db, mute}
  switches: {},
  swRead: null,
  telemetry: [],
  error: null,
};

const $ = (sel) => document.querySelector(sel);

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

function notice(text) {
  const el = $("#notice");
  if (!text) { el.hidden = true; return; }
  $("#notice-text").textContent = text;
  el.hidden = false;
}

function setChip(el, text, kind) {
  el.textContent = text;
  el.className = "chip" + (kind ? " chip--" + kind : "");
}

/* ---------------- rendering ---------------- */

function renderPairs() {
  const host = $("#pairs");
  host.replaceChildren();
  for (let p = 0; p < VISIBLE_PAIRS; p++) {
    const out = state.outputs[String(p)] || { db: 0, mute: false };
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pair";
    btn.setAttribute("aria-current", String(p === state.pair));
    const name = document.createElement("span");
    name.textContent = PAIR_NAMES[p];
    const db = document.createElement("span");
    db.className = "pair__db";
    db.textContent = out.mute ? "muted" : fmtDb(out.db);
    btn.append(name, db);
    btn.addEventListener("click", () => {
      state.pair = p;
      renderPairs();
      renderStrips();
    });
    host.append(btn);
  }
}

function stripFor(ch) {
  const key = state.pair + ":" + ch;
  if (!state.strips[key]) state.strips[key] = { level_db: -96, pan: 0, mute: true };
  return state.strips[key];
}

function buildStrip(input) {
  const s = stripFor(input.ch);
  const el = document.createElement("div");
  el.className = "strip" + (s.mute ? " strip--muted" : "");
  el.dataset.ch = input.ch;

  const name = document.createElement("span");
  name.className = "strip__name";
  name.textContent = input.name;
  name.title = input.name;

  const dbBtn = document.createElement("button");
  dbBtn.type = "button";
  dbBtn.className = "strip__db";
  dbBtn.textContent = fmtDb(s.level_db);
  dbBtn.title = "Click to type a level";
  dbBtn.setAttribute("aria-label", input.name + " level, " + fmtDb(s.level_db) + " dB, editable");
  dbBtn.addEventListener("click", () => editLevel(el, input));

  const fader = document.createElement("div");
  fader.className = "fader";
  fader.setAttribute("role", "slider");
  fader.tabIndex = 0;
  fader.setAttribute("aria-label", input.name + " level");
  fader.setAttribute("aria-valuemin", "-96");
  fader.setAttribute("aria-valuemax", "10");
  fader.innerHTML = '<div class="fader__track"></div><div class="fader__fill"></div>' +
                    '<div class="fader__unity"></div><div class="fader__thumb"></div>' +
                    [-12, -24, -48].map((db) =>
                      '<span class="fader__tick" style="bottom:' + (posFromDb(db) * 100) + '%"></span>').join('');

  const pan = document.createElement("div");
  pan.className = "pan";
  pan.setAttribute("role", "slider");
  pan.tabIndex = 0;
  pan.setAttribute("aria-label", input.name + " pan");
  pan.setAttribute("aria-valuemin", "-1");
  pan.setAttribute("aria-valuemax", "1");
  pan.innerHTML = '<div class="pan__track"></div>' +
                  '<span class="pan__tick" style="left:0"></span>' +
                  '<span class="pan__tick" style="left:50%"></span>' +
                  '<span class="pan__tick" style="left:100%"></span>' +
                  '<div class="pan__thumb"></div>';

  const mute = document.createElement("button");
  mute.type = "button";
  mute.className = "mute";
  mute.textContent = "MUTE";
  mute.setAttribute("aria-pressed", String(s.mute));
  mute.setAttribute("aria-label", input.name + " mute");

  el.append(name, dbBtn, fader, pan, mute);
  paintStrip(el, s);

  attachFader(el, fader, input);
  attachPan(el, pan, input);
  mute.addEventListener("click", () => {
    const cur = stripFor(input.ch);
    writeStrip(input.ch, { mute: !cur.mute });
  });

  return el;
}

function paintStrip(el, s) {
  el.classList.toggle("strip--muted", !!s.mute);
  const pos = posFromDb(s.level_db);
  el.querySelector(".fader__fill").style.height = (pos * 100) + "%";
  el.querySelector(".fader__thumb").style.bottom = (pos * 100) + "%";
  const unity = el.querySelector(".fader__unity");
  unity.style.bottom = (posFromDb(0) * 100) + "%";
  el.querySelector(".pan__thumb").style.left = ((s.pan + 1) / 2 * 100) + "%";
  el.querySelector(".strip__db").textContent = fmtDb(s.level_db);
  const muteBtn = el.querySelector(".mute");
  muteBtn.setAttribute("aria-pressed", String(!!s.mute));
  muteBtn.textContent = s.mute ? "MUTED" : "MUTE";
  el.querySelector(".fader").setAttribute("aria-valuenow", s.level_db.toFixed(1));
  el.querySelector(".fader").setAttribute("aria-valuetext", fmtDb(s.level_db) + " dB");
  el.querySelector(".pan").setAttribute("aria-valuenow", s.pan.toFixed(2));
  el.querySelector(".pan").setAttribute("aria-valuetext",
    s.pan <= -0.99 ? "hard left" : s.pan >= 0.99 ? "hard right" :
    Math.abs(s.pan) < 0.01 ? "centre" : (s.pan < 0 ? "left " : "right ") + Math.round(Math.abs(s.pan) * 100) + "%");
}

function attachFader(el, fader, input) {
  let dragging = false;
  const applyFrom = (clientY) => {
    const r = fader.getBoundingClientRect();
    const pos = 1 - (clientY - r.top) / r.height;
    const s = stripFor(input.ch);
    s.level_db = Math.round(dbFromPos(pos) * 10) / 10;
    if (s.level_db > -0.05 && s.level_db < 0.05) s.level_db = 0;
    paintStrip(el, s);
  };
  fader.addEventListener("pointerdown", (ev) => {
    dragging = true;
    fader.setPointerCapture(ev.pointerId);
    applyFrom(ev.clientY);
    ev.preventDefault();
  });
  fader.addEventListener("pointermove", (ev) => { if (dragging) applyFrom(ev.clientY); });
  fader.addEventListener("pointerup", (ev) => {
    if (!dragging) return;
    dragging = false;
    fader.releasePointerCapture(ev.pointerId);
    const s = stripFor(input.ch);
    writeStrip(input.ch, { level_db: s.level_db });
  });
  fader.addEventListener("keydown", (ev) => {
    const s = stripFor(input.ch);
    const step = ev.shiftKey ? 0.1 : 1;
    if (ev.key === "ArrowUp" || ev.key === "ArrowRight") { s.level_db = Math.min(10, s.level_db + step); }
    else if (ev.key === "ArrowDown" || ev.key === "ArrowLeft") { s.level_db = Math.max(-96, s.level_db - step); }
    else if (ev.key === "Home") { s.level_db = 10; }
    else if (ev.key === "End") { s.level_db = -96; }
    else return;
    ev.preventDefault();
    s.level_db = Math.round(s.level_db * 10) / 10;
    paintStrip(el, s);
    writeStrip(input.ch, { level_db: s.level_db });
  });
  fader.addEventListener("dblclick", () => {
    const s = stripFor(input.ch);
    s.level_db = s.level_db > -50 ? -96 : 0;
    paintStrip(el, s);
    writeStrip(input.ch, { level_db: s.level_db });
  });
}

function attachPan(el, pan, input) {
  let dragging = false;
  const applyFrom = (clientX) => {
    const r = pan.getBoundingClientRect();
    let p = (clientX - r.left) / r.width * 2 - 1;
    p = Math.max(-1, Math.min(1, p));
    if (Math.abs(p) < 0.04) p = 0;
    const s = stripFor(input.ch);
    s.pan = Math.round(p * 100) / 100;
    paintStrip(el, s);
  };
  pan.addEventListener("pointerdown", (ev) => {
    dragging = true;
    pan.setPointerCapture(ev.pointerId);
    applyFrom(ev.clientX);
    ev.preventDefault();
  });
  pan.addEventListener("pointermove", (ev) => { if (dragging) applyFrom(ev.clientX); });
  pan.addEventListener("pointerup", (ev) => {
    if (!dragging) return;
    dragging = false;
    pan.releasePointerCapture(ev.pointerId);
    writeStrip(input.ch, { pan: stripFor(input.ch).pan });
  });
  pan.addEventListener("dblclick", () => {
    const s = stripFor(input.ch);
    s.pan = 0;
    paintStrip(el, s);
    writeStrip(input.ch, { pan: 0 });
  });
  pan.addEventListener("keydown", (ev) => {
    const s = stripFor(input.ch);
    if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
      s.pan = Math.max(-1, Math.min(1, s.pan + (ev.key === "ArrowLeft" ? -0.1 : 0.1)));
      if (Math.abs(s.pan) < 0.04) s.pan = 0;
      s.pan = Math.round(s.pan * 100) / 100;
      ev.preventDefault();
      paintStrip(el, s);
      writeStrip(input.ch, { pan: s.pan });
    }
  });
}

function editLevel(el, input) {
  const s = stripFor(input.ch);
  const cur = el.querySelector(".strip__db");
  const box = document.createElement("input");
  box.type = "text";
  box.value = s.level_db.toFixed(1);
  box.className = "strip__db";
  box.style.width = "48px";
  box.setAttribute("aria-label", input.name + " level in dB");
  cur.replaceWith(box);
  box.focus();
  box.select();
  const commit = (ok) => {
    if (ok) {
      const v = parseFloat(box.value.replace(",", "."));
      if (!Number.isNaN(v)) {
        s.level_db = Math.max(-96, Math.min(10, v));
        writeStrip(input.ch, { level_db: s.level_db });
      }
    }
    paintStrip(el, s);
    box.replaceWith(el.querySelector(".strip__db") === box ? document.createElement("span") : el.querySelector(".strip__db"));
    renderStrips();
  };
  box.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") commit(true);
    if (ev.key === "Escape") commit(false);
  });
  box.addEventListener("blur", () => commit(true));
}

function updateSubtitle() {
  const inputs = state.info?.inputs || [];
  const live = inputs.filter((i) => {
    const s = state.strips[state.pair + ":" + i.ch];
    return s && !s.mute && s.level_db > -95.9;
  }).length;
  $("#mix-sub").textContent = live + " of " + inputs.length + " channels feeding " + PAIR_NAMES[state.pair];
}

function renderStrips() {
  const host = $("#groups");
  host.replaceChildren();
  $("#mix-title").textContent = PAIR_NAMES[state.pair];
  updateSubtitle();

  const groups = new Map();
  for (const input of (state.info?.inputs || [])) {
    if (!groups.has(input.group)) groups.set(input.group, []);
    groups.get(input.group).push(input);
  }
  for (const [group, inputs] of groups) {
    const wrap = document.createElement("div");
    wrap.className = "group";
    const head = document.createElement("div");
    head.className = "group__head";
    head.innerHTML = '<span class="group__name"></span><span class="group__rule"></span>' +
                     '<span class="group__count"></span>';
    head.querySelector(".group__name").textContent = group;
    head.querySelector(".group__count").textContent = inputs.length + " ch";
    const strips = document.createElement("div");
    strips.className = "strips";
    for (const input of inputs) strips.append(buildStrip(input));
    wrap.append(head, strips);
    host.append(wrap);
  }
}

function renderOutputs() {
  const host = $("#outfaders");
  host.replaceChildren();
  for (let p = 0; p < VISIBLE_PAIRS; p++) {
    const out = state.outputs[String(p)] || { db: 0, mute: false };
    const el = document.createElement("div");
    el.className = "out";
    el.innerHTML = '<span class="out__name"></span>' +
      '<div class="fader" role="slider" tabindex="0" aria-valuemin="-96" aria-valuemax="10">' +
      '<div class="fader__track"></div><div class="fader__fill"></div>' +
      '<div class="fader__unity"></div><div class="fader__thumb"></div></div>' +
      '<span class="out__db"></span>';
    el.querySelector(".out__name").textContent = PAIR_NAMES[p];
    el.querySelector(".out__db").textContent = out.mute ? "muted" : fmtDb(out.db);
    const fader = el.querySelector(".fader");
    const pos = posFromDb(out.db);
    fader.querySelector(".fader__fill").style.height = (pos * 100) + "%";
    fader.querySelector(".fader__thumb").style.bottom = (pos * 100) + "%";
    fader.querySelector(".fader__unity").style.bottom = (posFromDb(0) * 100) + "%";
    fader.setAttribute("aria-label", PAIR_NAMES[p] + " output level");
    fader.setAttribute("aria-valuenow", out.db.toFixed(1));

    let dragging = false;
    const apply = (clientY) => {
      const r = fader.getBoundingClientRect();
      const o = state.outputs[String(p)] || (state.outputs[String(p)] = { db: 0, mute: false });
      o.db = Math.round(dbFromPos(1 - (clientY - r.top) / r.height) * 10) / 10;
      const q = posFromDb(o.db);
      fader.querySelector(".fader__fill").style.height = (q * 100) + "%";
      fader.querySelector(".fader__thumb").style.bottom = (q * 100) + "%";
      el.querySelector(".out__db").textContent = fmtDb(o.db);
    };
    fader.addEventListener("pointerdown", (ev) => {
      dragging = true; fader.setPointerCapture(ev.pointerId); apply(ev.clientY); ev.preventDefault();
    });
    fader.addEventListener("pointermove", (ev) => { if (dragging) apply(ev.clientY); });
    fader.addEventListener("pointerup", (ev) => {
      if (!dragging) return;
      dragging = false; fader.releasePointerCapture(ev.pointerId);
      writeOutput(p, { db: state.outputs[String(p)].db });
    });
    fader.addEventListener("keydown", (ev) => {
      const o = state.outputs[String(p)] || (state.outputs[String(p)] = { db: 0, mute: false });
      const step = ev.shiftKey ? 0.1 : 1;
      if (ev.key === "ArrowUp") o.db = Math.min(10, o.db + step);
      else if (ev.key === "ArrowDown") o.db = Math.max(-96, o.db - step);
      else return;
      ev.preventDefault();
      o.db = Math.round(o.db * 10) / 10;
      el.querySelector(".out__db").textContent = fmtDb(o.db);
      const q = posFromDb(o.db);
      fader.querySelector(".fader__fill").style.height = (q * 100) + "%";
      fader.querySelector(".fader__thumb").style.bottom = (q * 100) + "%";
      writeOutput(p, { db: o.db });
    });
    host.append(el);
  }
}

const SWITCH_DEFS = [
  { name: "48v", label: "Phantom", on: "on", off: "off" },
  { name: "line", label: "Input 1/2", on: "line", off: "preamp" },
  { name: "ab", label: "Phones", on: "3/4", off: "1/2" },
  { name: "mute", label: "Main out", on: "muted", off: "open" },
];

function renderSwitches() {
  const host = $("#switches");
  host.replaceChildren();
  for (const def of SWITCH_DEFS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sw";
    const live = state.swRead ? !!state.swRead[def.name] : !!state.switches[def.name];
    btn.setAttribute("aria-pressed", String(live));
    btn.innerHTML = '<span class="sw__label"></span><span class="sw__state"></span>';
    btn.querySelector(".sw__label").textContent = def.label;
    btn.querySelector(".sw__state").textContent = live ? def.on : def.off;
    btn.addEventListener("click", () => {
      const next = !(state.swRead ? !!state.swRead[def.name] : !!state.switches[def.name]);
      writeSwitch(def.name, next);
    });
    host.append(btn);
  }
}

function renderTelemetry() {
  const host = $("#telemetry");
  host.replaceChildren();
  state.telemetry.forEach((v, i) => {
    const el = document.createElement("span");
    el.className = "tel";
    el.textContent = String(v);
    el.title = "state packet field " + (4 + i);
    host.append(el);
  });
}

/* ---------------- writes ---------------- */

let pending = {};
let pendingTimer = null;

function queueWrite(key, fn) {
  pending[key] = fn;
  clearTimeout(pendingTimer);
  pendingTimer = setTimeout(flushWrites, 90);
}

async function flushWrites() {
  const jobs = Object.values(pending);
  pending = {};
  for (const job of jobs) {
    try { await job(); } catch (err) { notice(err.message); }
  }
}

function writeStrip(ch, patch) {
  const key = "strip:" + state.pair + ":" + ch;
  queueWrite(key, async () => {
    const s = stripFor(ch);
    Object.assign(s, patch);
    await api("/api/strip", Object.assign({ pair: state.pair, input: ch }, s));
    markWritten();
    renderPairs();
    updateSubtitle();
  });
}

function writeOutput(pair, patch) {
  queueWrite("out:" + pair, async () => {
    const o = state.outputs[String(pair)] = Object.assign({ db: 0, mute: false }, state.outputs[String(pair)], patch);
    await api("/api/output", Object.assign({ pair }, o));
    markWritten();
    renderPairs();
    renderOutputs();
  });
}

async function writeSwitch(name, value) {
  try {
    await api("/api/switch", { name, value });
    state.switches[name] = value;
    if (state.swRead) state.swRead[name] = value ? 1 : 0;
    renderSwitches();
    markWritten();
  } catch (err) { notice(err.message); }
}

function markWritten() {
  const t = new Date();
  $("#written").textContent = "written " + t.toTimeString().slice(0, 8);
}

/* ---------------- boot ---------------- */

function applyInfo(info) {
  state.info = info;
  state.strips = Object.assign({}, info.state.strips, state.strips);
  state.outputs = Object.assign({}, info.state.outputs, state.outputs);
  state.switches = Object.assign({}, info.state.switches, state.switches);
  state.swRead = info.switches_read;
  state.telemetry = info.telemetry || [];
  state.error = info.error;

  if (info.device) {
    setChip($("#chip-link"), "connected", "ok");
    $("#foot-device").textContent = "usb " + info.device.vid + ":" + info.device.pid +
      " · bus " + info.device.bus + " addr " + info.device.addr + " · ALSA card " + info.card;
  } else {
    setChip($("#chip-link"), "no device", "err");
    $("#foot-device").textContent = info.error || "device not found";
  }

  if (info.alsa?.rates) {
    const rates = info.alsa.rates.split(",").map((r) => parseInt(r, 10)).filter(Boolean);
    if (rates.length) {
      const min = Math.min(...rates) / 1000;
      const max = Math.max(...rates) / 1000;
      setChip($("#chip-rate"), min === max ? min + " kHz" : min + "-" + max + " kHz");
    }
  } else {
    setChip($("#chip-rate"), "rate unknown");
  }
  const clock = info.alsa?.clock_source;
  setChip($("#chip-clock"), "clock " + (clock === 0 ? "internal" : clock === 1 ? "S/PDIF" : clock === 2 ? "ADAT" : "unknown"));

  if (info.error) notice(info.error); else notice(null);
  $("#written").textContent = info.state.applied_at
    ? "last write " + info.state.applied_at
    : "not pushed to device";

  renderPairs();
  renderStrips();
  renderOutputs();
  renderSwitches();
  renderTelemetry();
}

async function boot() {
  const savedTheme = localStorage.getItem("uc-theme");
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;
  else if (window.matchMedia("(prefers-color-scheme: light)").matches)
    document.documentElement.dataset.theme = "light";

  try {
    applyInfo(await api("/api/info"));
  } catch (err) {
    notice("Cannot reach the daemon: " + err.message);
    setChip($("#chip-link"), "daemon offline", "err");
  }

  try {
    const presets = await api("/api/presets");
    const sel = $("#presets");
    for (const name of presets) {
      const opt = document.createElement("option");
      opt.value = name; opt.textContent = name;
      sel.append(opt);
    }
  } catch { /* presets are optional */ }

  const events = new EventSource("/api/events");
  events.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    state.telemetry = data.telemetry;
    state.swRead = data.switches_read;
    state.error = data.error;
    if (data.error) notice(data.error); else notice(null);
    renderTelemetry();
    renderSwitches();
    $("#written").textContent = data.applied_at
      ? "last write " + data.applied_at
      : "not pushed to device";
  };
  events.onerror = () => setChip($("#chip-link"), "stream lost", "err");

  $("#apply").addEventListener("click", async () => {
    const btn = $("#apply");
    btn.disabled = true;
    btn.textContent = "Pushing…";
    try {
      const res = await api("/api/apply", {});
      $("#written").textContent = "last write " + res.applied_at;
      notice(null);
    } catch (err) {
      notice("Push failed: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Push session";
    }
  });

  $("#clear-pair").addEventListener("click", () => {
    for (const input of state.info.inputs) {
      const s = stripFor(input.ch);
      if (!s.mute) { s.mute = true; writeStrip(input.ch, { mute: true }); }
    }
    renderStrips();
  });

  $("#preset-save").addEventListener("click", async () => {
    const name = prompt("Preset name");
    if (!name) return;
    try {
      await api("/api/preset", { name });
      const opt = document.createElement("option");
      opt.value = name; opt.textContent = name;
      $("#presets").append(opt);
      notice(null);
    } catch (err) { notice("Save failed: " + err.message); }
  });

  $("#presets").addEventListener("change", async (ev) => {
    if (!ev.target.value) return;
    try {
      await api("/api/preset/load", { name: ev.target.value });
      applyInfo(await api("/api/info"));
    } catch (err) { notice("Load failed: " + err.message); }
  });

  $("#theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("uc-theme", next);
  });

  $("#notice-retry").addEventListener("click", async () => {
    try { applyInfo(await api("/api/info")); } catch (err) { notice(err.message); }
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "/" && document.activeElement.tagName !== "INPUT") {
      ev.preventDefault();
      document.querySelector(".pair")?.focus();
    }
  });
}

boot();
