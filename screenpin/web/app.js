"use strict";
const KEY = window.SP_KEY;
const $ = (s) => document.querySelector(s);
const el = (tag, cls, txt) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt != null) n.textContent = txt;
  return n;
};

let S = null;              // latest state
let rev = -1;
let filter = "";
let onlyAway = false;
let dragHwnd = null;

/* ------------------------------------------------------------------ api */
async function api(a, extra) {
  const body = Object.assign({ a }, extra || {});
  const r = await fetch("/api/action?k=" + encodeURIComponent(KEY), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (j.state) apply(j.state);
  return j;
}

async function poll() {
  for (;;) {
    try {
      const r = await fetch("/api/state?k=" + encodeURIComponent(KEY) +
                            "&since=" + rev);
      if (!r.ok) throw new Error(r.status);
      apply(await r.json());
    } catch (e) {
      setStatus("ขาดการเชื่อมต่อกับ ScreenPin", "bad");
      await new Promise((r) => setTimeout(r, 900));
    }
  }
}

/* ------------------------------------------------------------------ render */
function apply(state) {
  if (!state || state.rev === rev) return;
  const first = S === null;
  const prev = S;
  S = state;
  rev = state.rev;
  renderBoard();
  renderRows();
  if (first || JSON.stringify(prev.known) !== JSON.stringify(S.known) ||
      JSON.stringify(prev.self) !== JSON.stringify(S.self)) {
    renderMons();
    renderChain();
  }
  if (first || JSON.stringify(prev.settings) !== JSON.stringify(S.settings) ||
      prev.autostart !== S.autostart) renderOpts();
  if (first || JSON.stringify(prev.hotkeys) !== JSON.stringify(S.hotkeys) ||
      JSON.stringify(prev.hotkey_status) !== JSON.stringify(S.hotkey_status))
    renderHotkeys();
  const st = S.status || {};
  setStatus(st.text || "พร้อมใช้งาน", st.level || "info");
  $("#cfgpath").textContent = S.config_path || "";
}

function setStatus(text, level) {
  const bar = $("#status");
  bar.className = "status " + (level === "info" ? "" : level || "");
  $("#status-text").textContent = text;
}

/* --------------------------------------------------------------- board */
function iconUrl(win) {
  return "/icon/" + win.hwnd + ".png?k=" + encodeURIComponent(KEY);
}

function shortName(win) {
  return (win.exe || "").replace(/\.exe$/i, "");
}

function boardSig() {
  return JSON.stringify([
    S.monitors.map((m) => [m.key, m.tag, m.slot, m.w, m.here]),
    S.windows.map((x) => [x.hwnd, x.mon, x.mode, x.min, x.home, x.exe]),
  ]);
}

function renderBoard(force) {
  const board = $("#board");
  const sig = boardSig();
  if (!force && (sig === board.dataset.sig || dragHwnd !== null)) return;
  board.dataset.sig = sig;
  board.innerHTML = "";
  if (!S.monitors.length) return;

  const total = S.monitors.reduce((a, m) => a + m.w, 0) || 1;
  for (const m of S.monitors) {
    const card = el("div", "mon" + (m.here ? " self" : ""));
    card.style.flex = (m.w / total) + " 1 0";

    const head = el("div", "mon-head");
    const slot = el("div", "mon-slot" + (m.slot ? "" : " none"),
                    m.slot ? String(m.slot) : "·");
    slot.title = m.slot ? "ปุ่มลัด Ctrl+Alt+" + m.slot : "ยังไม่ได้ตั้ง slot";
    head.appendChild(slot);
    const name = el("div", "mon-name", m.tag);
    name.title = "คลิกเพื่อเปลี่ยนชื่อจอ";
    name.onclick = () => renameMonitor(m.key, m.tag);
    head.appendChild(name);
    const meta = el("div", "mon-meta");
    if (m.here) {
      const dot = el("span", "mon-here");
      dot.title = "ScreenPin อยู่จอนี้";
      meta.appendChild(dot);
    }
    meta.appendChild(el("span", "mon-res", m.w + "×" + m.h + (m.primary ? " ★" : "")));
    const ev = el("button", "mon-evac", "อพยพ →");
    ev.title = "ย้ายทุกหน้าต่างบนจอนี้ไปจอถัดไป (ใช้ก่อนปิดจอ) — จำจอเดิมไว้ให้";
    ev.onclick = (e) => { e.stopPropagation(); api("evacuate", { key: m.key, dir: 1 }); };
    meta.appendChild(ev);
    head.appendChild(meta);
    card.appendChild(head);

    const apps = el("div", "apps");
    const mine = S.windows.filter((x) => x.mon === m.key);
    if (!mine.length) apps.appendChild(el("div", "mon-empty", "ว่าง"));
    for (const win of mine) apps.appendChild(buildApp(win));
    card.appendChild(apps);

    const over = (e) => {
      if (dragHwnd === null) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      card.classList.add("drop");
    };
    card.addEventListener("dragover", over);
    card.addEventListener("dragenter", over);
    card.addEventListener("dragleave", (e) => {
      if (!card.contains(e.relatedTarget)) card.classList.remove("drop");
    });
    card.addEventListener("drop", (e) => {
      e.preventDefault();
      card.classList.remove("drop");
      const hwnd = dragHwnd;
      dragHwnd = null;
      if (hwnd) api("move", { hwnd, key: m.key });
    });
    board.appendChild(card);
  }
}

function buildApp(win) {
  const away = win.home && win.mon_tag && win.home !== win.mon_tag;
  const node = el("div", "app" + (win.min ? " min" : "") +
                  (win.mode === "pin" ? " pinned" : away ? " away" : ""));
  node.draggable = true;
  node.dataset.hwnd = String(win.hwnd);
  const note = (win.mode === "pin" ? "\n📌 ปักหมุดไว้ที่ " + win.home
    : away ? "\n⚠ จำไว้ว่าอยู่ " + win.home : "")
    + (win.min ? "\n▾ ย่ออยู่ — ลากย้ายได้ คลิกเพื่อเรียกขึ้นมา" : "");
  node.title = (win.exe || "") + "\n" + win.title + note;

  if (win.icon) {
    const img = el("img");
    img.src = iconUrl(win);
    img.alt = "";
    img.draggable = false;
    img.onerror = () => { img.replaceWith(fallbackIcon(win)); };
    node.appendChild(img);
  } else {
    node.appendChild(fallbackIcon(win));
  }
  if (win.mode === "pin") node.appendChild(el("span", "badge", "📌"));
  else if (away) node.appendChild(el("span", "badge", "⚠"));
  else if (win.min) node.appendChild(el("span", "badge dim", "▾"));
  node.appendChild(el("div", "cap", shortName(win)));

  node.addEventListener("dragstart", (e) => {
    dragHwnd = win.hwnd;
    node.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(win.hwnd));
  });
  node.addEventListener("dragend", () => {
    dragHwnd = null;
    node.classList.remove("dragging");
    document.querySelectorAll(".mon.drop").forEach((c) => c.classList.remove("drop"));
    renderBoard(true);
  });
  node.addEventListener("click", () => api("focus", { hwnd: win.hwnd }));
  node.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    api("pin", { hwnd: win.hwnd });
  });
  return node;
}

function fallbackIcon(win) {
  return el("div", "fallback", (shortName(win)[0] || "?").toUpperCase());
}

/* --------------------------------------------------------------- rows */
function renderRows() {
  const box = $("#rows");
  const f = filter.trim().toLowerCase();
  let list = S.windows;
  if (f) list = list.filter((x) =>
    (x.exe + " " + x.title).toLowerCase().includes(f));
  if (onlyAway) list = list.filter((x) => x.home && x.mon_tag &&
    x.home !== x.mon_tag);

  $("#wcount").textContent = list.length + " / " + S.windows.length + " หน้าต่าง";
  $("#empty").hidden = list.length > 0;

  const seen = new Set();
  for (const win of list) {
    const id = "w" + win.hwnd;
    seen.add(id);
    let row = document.getElementById(id);
    if (!row) { row = buildRow(win); box.appendChild(row); }
    updateRow(row, win);
  }
  for (const node of Array.from(box.children))
    if (!seen.has(node.id)) node.remove();
  // keep DOM order in sync with the sorted list
  list.forEach((win, i) => {
    const node = document.getElementById("w" + win.hwnd);
    if (node && box.children[i] !== node) box.insertBefore(node, box.children[i]);
  });
}

function buildRow(win) {
  const row = el("div", "row");
  row.id = "w" + win.hwnd;
  row.draggable = true;
  row.appendChild(el("div", "exe"));
  row.appendChild(el("div", "title"));
  row.appendChild(el("div", "state"));
  row.appendChild(el("div", "act"));
  row.ondragstart = (e) => {
    dragHwnd = win.hwnd;
    row.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(win.hwnd));
  };
  row.ondragend = () => { dragHwnd = null; row.classList.remove("dragging"); };
  row.ondblclick = () => api("move_dir", { hwnd: win.hwnd, dir: 1 });
  return row;
}

function updateRow(row, win) {
  const away = win.home && win.mon_tag && win.home !== win.mon_tag;
  row.className = "row" + (win.mode === "pin" ? " pinned" : "") +
                  (away ? " away" : "");
  const exe = row.children[0], title = row.children[1];
  if (exe.textContent !== win.exe) { exe.textContent = win.exe; exe.title = win.app; }
  const t = (win.min ? "▾ " : win.max ? "▣ " : "") + win.title;
  if (title.textContent !== t) { title.textContent = t; title.title = win.title; }

  const state = row.children[2];
  const wanted = JSON.stringify([win.mon_tag, win.home, away, win.min, win.max]);
  if (state.dataset.sig !== wanted) {
    state.dataset.sig = wanted;
    state.innerHTML = "";
    if (win.mon_tag) state.appendChild(el("span", "chip now", win.mon_tag));
    if (win.home && away)
      state.appendChild(el("span", "chip miss", "จำไว้: " + win.home));
    else if (win.home)
      state.appendChild(el("span", "chip home mini", "จำแล้ว"));
  }

  const act = row.children[3];
  const sig = JSON.stringify([S.monitors.map((m) => [m.key, m.slot, m.tag]),
                              win.mon, win.mode]);
  if (act.dataset.sig === sig) return;
  act.dataset.sig = sig;
  act.innerHTML = "";
  for (const m of S.monitors) {
    const b = el("button", "mbtn" + (m.key === win.mon ? " cur" : ""),
                 m.slot ? String(m.slot) : m.tag.slice(0, 3));
    b.title = "ย้ายไป " + m.tag;
    if (m.key !== win.mon)
      b.onclick = (e) => { e.stopPropagation(); api("move", { hwnd: win.hwnd, key: m.key }); };
    act.appendChild(b);
  }
  const pin = el("button", "pin" + (win.mode === "pin" ? " on" : ""), "📌");
  pin.title = win.mode === "pin"
    ? "ปักหมุดอยู่ — คลิกเพื่อเลิก" : "ปักหมุดแอพนี้ไว้จอนี้ถาวร";
  pin.onclick = (e) => { e.stopPropagation(); api("pin", { hwnd: win.hwnd }); };
  act.appendChild(pin);
}

/* --------------------------------------------------------------- monitors tab */
function renderMons() {
  const box = $("#mons");
  box.innerHTML = "";
  for (const m of S.known) {
    const r = el("div", "mrow" + (m.online ? "" : " off"));
    r.appendChild(el("span", "live"));
    const info = el("div");
    info.appendChild(el("div", "name", m.tag));
    info.appendChild(el("div", "meta",
      (m.online ? "ออนไลน์" : "ปิดอยู่ · เห็นล่าสุด " + (m.last_seen || "-")) +
      " · " + (m.size[0] || "?") + "×" + (m.size[1] || "?") + " · " + m.key));
    r.appendChild(info);

    const sel = el("select");
    sel.title = "slot สำหรับปุ่มลัด Ctrl+Alt+เลข";
    for (let i = 0; i <= 9; i++) {
      const o = el("option", null, i === 0 ? "ไม่มี slot" : "slot " + i);
      o.value = String(i);
      if (i === (m.slot || 0)) o.selected = true;
      sel.appendChild(o);
    }
    sel.onchange = () => api("set_slot", { key: m.key, slot: +sel.value });
    r.appendChild(sel);

    const ren = el("button", "btn ghost sm", "เปลี่ยนชื่อ");
    ren.onclick = () => renameMonitor(m.key, m.tag);
    r.appendChild(ren);

    const del = el("button", "btn ghost sm", "ลบ");
    del.disabled = m.online;
    del.style.opacity = m.online ? .35 : 1;
    del.title = m.online ? "จอนี้ยังต่ออยู่" : "ลบจอที่เลิกใช้แล้ว";
    del.onclick = () => { if (!m.online) api("delete_monitor", { key: m.key }); };
    r.appendChild(del);
    box.appendChild(r);
  }
}

function renderChain() {
  const box = $("#chain");
  box.innerHTML = "";
  const tags = S.known.map((m) => m.tag);
  const labels = ["จอหลัก", "จอรอง 1", "จอรอง 2"];
  for (let i = 0; i < 3; i++) {
    const wrap = el("div", "slotpick");
    wrap.appendChild(el("label", null, labels[i]));
    const sel = el("select");
    const none = el("option", null,
      i === 0 ? "(ไม่ตั้ง — อยู่จอเดิมที่เคยอยู่)" : "(ไม่ตั้ง)");
    none.value = "";
    sel.appendChild(none);
    for (const t of tags) {
      const online = S.monitors.some((m) => m.tag === t);
      const o = el("option", null, t + (online ? "" : "  · ปิดอยู่"));
      o.value = t;
      if (S.self.chain[i] === t) o.selected = true;
      sel.appendChild(o);
    }
    sel.onchange = saveChain;
    sel.dataset.idx = String(i);
    wrap.appendChild(sel);
    box.appendChild(wrap);
  }
  $("#follow").checked = !!S.self.follow;
}

function saveChain() {
  const chain = Array.from($("#chain").querySelectorAll("select"))
    .map((s) => s.value).filter(Boolean);
  api("self_chain", { chain, follow: $("#follow").checked });
}

/* --------------------------------------------------------------- settings */
const OPTS = [
  ["auto_restore", "คืนหน้าต่างกลับจอเดิมอัตโนมัติเมื่อจอกลับมา"],
  ["learn", "จำจอที่แต่ละหน้าต่างอยู่ให้อัตโนมัติ"],
  ["place_new_windows", "เปิดแอพใหม่ → ส่งไปจอที่จำไว้ทันที"],
  ["hotkeys_enabled", "เปิดใช้ปุ่มลัดทั่วเครื่อง"],
  ["notify", "แจ้งเตือนที่ tray เวลาจัดจอให้"],
  ["close_quits", "กดปิดหน้าต่าง = ออกจากโปรแกรมเลย (ไม่ค้างใน tray)"],
];

function renderOpts() {
  const box = $("#opts");
  box.innerHTML = "";
  for (const [key, label] of OPTS) {
    const l = el("label", "switch");
    const inp = el("input");
    inp.type = "checkbox";
    inp.checked = !!S.settings[key];
    inp.onchange = () => api("setting", { key, value: inp.checked });
    l.appendChild(inp);
    l.appendChild(el("span", "track"));
    l.appendChild(el("span", "lbl", label));
    box.appendChild(l);
  }
  $("#autostart").checked = !!S.autostart;
  $("#startmenu").checked = !!S.start_menu;
}

const HK_NAMES = {
  move_left: "ย้ายหน้าต่าง → จอซ้าย",
  move_right: "ย้ายหน้าต่าง → จอขวา",
  picker: "เปิดตัวเลือกจอ (overlay)",
  pin_here: "ปักหมุดหน้าต่างนี้ไว้จอนี้",
  slot_1: "ส่งไปจอ slot 1", slot_2: "ส่งไปจอ slot 2",
  slot_3: "ส่งไปจอ slot 3", slot_4: "ส่งไปจอ slot 4",
  slot_5: "ส่งไปจอ slot 5", slot_6: "ส่งไปจอ slot 6",
  evacuate_left: "อพยพทั้งจอ → ซ้าย",
  evacuate_right: "อพยพทั้งจอ → ขวา",
  show_app: "เปิดหน้าต่าง ScreenPin",
};

function renderHotkeys() {
  const box = $("#hotkeys");
  box.innerHTML = "";
  const bad = new Set(S.hotkey_status.bad || []);
  for (const key of Object.keys(HK_NAMES)) {
    if (!(key in S.hotkeys)) continue;
    const row = el("div", "hk");
    row.appendChild(el("span", "name", HK_NAMES[key]));
    const btn = el("button", "key", S.hotkeys[key] || "— ว่าง —");
    btn.dataset.key = key;
    btn.dataset.val = S.hotkeys[key] || "";
    if (bad.has(S.hotkeys[key])) {
      btn.classList.add("bad");
      btn.title = "ปุ่มนี้ถูกโปรแกรมอื่นยึดไว้";
    }
    btn.onclick = () => captureHotkey(btn);
    row.appendChild(btn);
    box.appendChild(row);
  }
  const st = $("#hk-status");
  st.textContent = bad.size
    ? "ใช้งาน " + S.hotkey_status.ok + " ปุ่ม · ชนกับโปรแกรมอื่น: " +
      Array.from(bad).join(", ")
    : "ใช้งาน " + S.hotkey_status.ok + " ปุ่ม";
  st.className = "hk-status" + (bad.size ? " warn" : "");
}

const CODE_MAP = {
  ArrowLeft: "Left", ArrowRight: "Right", ArrowUp: "Up", ArrowDown: "Down",
  Space: "Space", Enter: "Enter", Escape: "Esc", Tab: "Tab",
  Home: "Home", End: "End", PageUp: "PgUp", PageDown: "PgDn",
  Insert: "Ins", Delete: "Del",
};

function captureHotkey(btn) {
  if (btn.classList.contains("rec")) return;
  const prev = btn.dataset.val;
  btn.classList.add("rec");
  btn.classList.remove("bad");
  btn.textContent = "กดปุ่มที่ต้องการ…";
  const stop = () => {
    btn.classList.remove("rec");
    window.removeEventListener("keydown", onKey, true);
    window.removeEventListener("blur", cancel);
  };
  const cancel = () => { btn.textContent = prev || "— ว่าง —"; stop(); };
  const onKey = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.code === "Escape") return cancel();
    if (e.code === "Backspace") {
      btn.dataset.val = "";
      btn.textContent = "— ว่าง —";
      return stop();
    }
    let base = null;
    if (e.code in CODE_MAP) base = CODE_MAP[e.code];
    else if (/^Key[A-Z]$/.test(e.code)) base = e.code.slice(3);
    else if (/^Digit[0-9]$/.test(e.code)) base = e.code.slice(5);
    else if (/^Numpad[0-9]$/.test(e.code)) base = "Num" + e.code.slice(6);
    else if (/^F([1-9]|1[0-9]|2[0-4])$/.test(e.code)) base = e.code;
    if (!base) return;                       // pure modifier - keep waiting
    const mods = [];
    if (e.ctrlKey) mods.push("Ctrl");
    if (e.altKey) mods.push("Alt");
    if (e.shiftKey) mods.push("Shift");
    if (e.metaKey) mods.push("Win");
    if (!mods.length) {
      btn.textContent = "ต้องมี Ctrl/Alt/Shift/Win ด้วย";
      return;
    }
    const combo = mods.concat(base).join("+");
    btn.dataset.val = combo;
    btn.textContent = combo;
    stop();
  };
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("blur", cancel);
}

/* --------------------------------------------------------------- modal */
let modalResolve = null;
function ask(title, sub, value) {
  $("#modal-title").textContent = title;
  $("#modal-sub").textContent = sub || "";
  const inp = $("#modal-input");
  inp.value = value || "";
  $("#modal").hidden = false;
  setTimeout(() => { inp.focus(); inp.select(); }, 20);
  return new Promise((res) => { modalResolve = res; });
}
function closeModal(v) {
  $("#modal").hidden = true;
  if (modalResolve) modalResolve(v);
  modalResolve = null;
}
async function renameMonitor(key, cur) {
  const v = await ask("ตั้งชื่อจอ", "ชื่อนี้จะถูกใช้อ้างอิงตลอด แม้ Windows สลับเลขจอ", cur);
  if (v && v !== cur) {
    const r = await api("rename_monitor", { key, tag: v });
    if (!r.ok) setStatus(r.msg, "bad");
  }
}

/* --------------------------------------------------------------- wiring */
$("#tabs").onclick = (e) => {
  const t = e.target.closest(".tab");
  if (!t) return;
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".page").forEach((p) =>
    p.classList.toggle("active", p.id === "page-" + t.dataset.tab));
  if (t.dataset.tab === "main") renderBoard(true);
};
$("#btn-reload").onclick = () => api("reconcile");
$("#btn-tray").onclick = () => api("hide");
$("#btn-place").onclick = () => api("place_self");
$("#follow").onchange = saveChain;
$("#search").oninput = (e) => { filter = e.target.value; renderRows(); };
$("#only-away").onchange = (e) => { onlyAway = e.target.checked; renderRows(); };
$("#autostart").onchange = (e) => api("autostart", { on: e.target.checked });
$("#startmenu").onchange = (e) => api("start_menu", { on: e.target.checked });
$("#btn-config").onclick = () => api("open_config");
$("#btn-quit").onclick = async () => {
  if (await ask("ออกจาก ScreenPin?", "พิมพ์ ok เพื่อยืนยัน", "") === "ok")
    api("quit");
};
$("#btn-hk-save").onclick = () => {
  const map = {};
  document.querySelectorAll(".hk .key").forEach((b) => { map[b.dataset.key] = b.dataset.val; });
  api("hotkeys", { map });
};
$("#btn-hk-reset").onclick = () => api("hotkeys_reset");
$("#modal-ok").onclick = () => closeModal($("#modal-input").value.trim());
$("#modal-cancel").onclick = () => closeModal(null);
$("#modal-input").onkeydown = (e) => {
  if (e.key === "Enter") closeModal($("#modal-input").value.trim());
  if (e.key === "Escape") closeModal(null);
};
window.addEventListener("resize", () => { if (S) renderBoard(true); });
document.addEventListener("keydown", (e) => {
  if (e.key === "f" && e.ctrlKey) { e.preventDefault(); $("#search").focus(); }
});

poll();
