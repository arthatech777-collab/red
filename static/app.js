// Kathaa front-end. No framework on purpose: fast to load on any phone.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const state = { look: "cinematic", aspect: "9:16", shots: 3, engines: [] };

// Rotating example pitches, in the languages our users actually write in.
const PITCHES = [
  "A grandmother in Dharwad teaching her granddaughter to make pedha, monsoon light through the window",
  "मुंबई की लोकल ट्रेन में एक लड़का खिड़की से बारिश देखता है, और मुस्कुराता है",
  "ಹಂಪಿಯ ಕಲ್ಲಿನ ರಥದ ಮುಂದೆ ಸೂರ್ಯೋದಯ, ಒಬ್ಬ ನೃತ್ಯಗಾರ್ತಿ ಭರತನಾಟ್ಯ ಮಾಡುತ್ತಿದ್ದಾಳೆ",
  "30-second ad: a steel tiffin opens and steam rises, a Chennai office lunch hour",
  "சென்னை மெரினா கடற்கரையில் காலை நேரம், ஒரு மீனவர் வலையை வீசுகிறார்",
];
let pi = 0;
const idea = $("#idea");
const rotate = () => { idea.placeholder = PITCHES[pi++ % PITCHES.length]; };
rotate(); setInterval(() => { if (!idea.value) rotate(); }, 4200);
idea.addEventListener("input", () => { $("#chars").textContent = idea.value.length; });

// chips
$$(".chips").forEach(group => group.addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  $$("button", group).forEach(x => x.classList.toggle("on", x === b));
  state[group.dataset.name] = b.dataset.v;
}));
const setShots = n => { state.shots = Math.max(1, Math.min(6, n)); $("#shotsN").textContent = state.shots; };
$("#minus").onclick = () => setShots(state.shots - 1);
$("#plus").onclick = () => setShots(state.shots + 1);

const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`);
  return data;
};

// studio health
(async () => {
  const h = $("#health");
  try {
    const s = await api("/api/status");
    state.engines = s.engines;
    const ok = s.writer === "gemini" && s.hf_token;
    h.classList.add(ok ? "ok" : "warn");
    $("b", h).textContent = ok ? "studio open" : (s.writer !== "gemini" ? "writer offline" : "guest GPU");
    h.title = `Writer: ${s.writer}. GPU token: ${s.hf_token ? "yes" : "no, using guest quota"}`;
  } catch { $("b", h).textContent = "server down"; }
})();

const note = t => { $("#deskNote").textContent = t || ""; };

// writer
$("#write").onclick = async () => {
  if (!idea.value.trim()) { idea.focus(); note("Start with a line about your story."); return; }
  const btn = $("#write"); btn.disabled = true; btn.textContent = "Writing…"; note("");
  try {
    const s = await api("/api/story", { method: "POST", body: JSON.stringify({
      idea: idea.value, language: $("#language").value, look: state.look, shots: state.shots }) });
    showBoard(s);
    if (s.warning) note(s.warning); else if (s.offline) note("Writer is offline, so this is a plain shot list. Add a Gemini key for a real one.");
  } catch (e) { note(e.message); }
  btn.disabled = false; btn.textContent = "Write the shot list";
};
$("#single").onclick = () => {
  if (!idea.value.trim()) { idea.focus(); note("Type the shot you want."); return; }
  showBoard({ title: "One shot", logline: "", shots: [{ prompt: idea.value, line: "", camera: "single take" }] });
};

function showBoard(s) {
  $("#board").hidden = false;
  $("#title").textContent = s.title || "Untitled";
  $("#logline").textContent = s.logline || "";
  const list = $("#shots"); list.innerHTML = "";
  (s.shots || []).forEach((sh, i) => list.appendChild(makeCard(sh, i)));
  $("#board").scrollIntoView({ behavior: "smooth" });
}

function makeCard(sh, i) {
  const el = $("#shotTpl").content.firstElementChild.cloneNode(true);
  $(".num", el).textContent = `SHOT ${String(i + 1).padStart(2, "0")}`;
  $(".cam", el).textContent = (sh.camera || "").toUpperCase();
  $(".prompt", el).value = sh.prompt || "";
  $(".line", el).value = sh.line || "";
  const eng = $(".engine", el);
  (state.engines.length ? state.engines : [{ id: "ltx", label: "Swift · LTX-Video", ready: true }])
    .forEach(e => { const o = new Option(e.label, e.id); o.disabled = !e.ready; eng.add(o); });

  const file = $("input[type=file]", el);
  file.onchange = async () => {
    if (!file.files[0]) return;
    const fd = new FormData(); fd.append("file", file.files[0]);
    try {
      const r = await fetch("/api/upload", { method: "POST", body: fd }).then(r => r.json());
      el.dataset.image = r.image_id;
      const img = $(".photo img", el); img.src = URL.createObjectURL(file.files[0]); img.hidden = false;
      $(".photo-btn", el).textContent = "Photo set";
    } catch { $(".photo-btn", el).textContent = "Upload failed"; }
  };
  $(".roll", el).onclick = () => roll(el);
  $(".del", el).onclick = () => el.remove();
  return el;
}

function setCardState(el, s, text) { el.dataset.state = s; $(".state", el).textContent = text || s; }

async function roll(el) {
  const btn = $(".roll", el); btn.disabled = true;
  $(".err", el).hidden = true;
  setCardState(el, "rolling", "queued");
  try {
    const { job_id } = await api("/api/render", { method: "POST", body: JSON.stringify({
      prompt: $(".prompt", el).value, engine: $(".engine", el).value, aspect: state.aspect,
      seconds: Number($(".secs", el).value), image_id: el.dataset.image || null }) });
    const t0 = Date.now();
    for (;;) {
      await new Promise(r => setTimeout(r, 2500));
      const j = await api(`/api/render/${job_id}`);
      const secs = Math.round((Date.now() - t0) / 1000);
      if (j.state === "queued") setCardState(el, "rolling", `waiting · ${secs}s`);
      if (j.state === "rolling") setCardState(el, "rolling", `rolling · ${String(Math.floor(secs/60)).padStart(2,"0")}:${String(secs%60).padStart(2,"0")}`);
      if (j.state === "done") { finish(el, j.video); break; }
      if (j.state === "failed") throw new Error(j.error);
    }
  } catch (e) {
    setCardState(el, "failed", "no take");
    const er = $(".err", el); er.textContent = e.message; er.hidden = false;
    $(".placeholder", el).hidden = true;
  }
  btn.disabled = false; btn.textContent = "Roll again";
}

function finish(el, src) {
  setCardState(el, "done", "in the can");
  $(".placeholder", el).hidden = true;
  const v = $("video", el); v.src = src; v.hidden = false; v.play().catch(() => {});
  const dl = $(".dl", el); dl.href = src; dl.hidden = false;
  addToReel({ src, caption: $(".prompt", el).value.slice(0, 80), at: Date.now() });
}

// reel (kept in the browser for the prototype)
const REEL_KEY = "kathaa.reel";
const loadReel = () => JSON.parse(localStorage.getItem(REEL_KEY) || "[]");
function addToReel(t) { const r = [t, ...loadReel()].slice(0, 40); localStorage.setItem(REEL_KEY, JSON.stringify(r)); drawReel(); }
function drawReel() {
  const r = loadReel(), strip = $("#reelStrip");
  $("#reelCount").textContent = r.length;
  if (!r.length) { strip.innerHTML = '<p class="empty">Nothing in the can yet. Your first take lands here.</p>'; return; }
  strip.innerHTML = "";
  r.forEach(t => {
    const d = document.createElement("div"); d.className = "take";
    d.innerHTML = `<video src="${t.src}" muted loop playsinline preload="metadata"></video><p></p>`;
    $("p", d).textContent = t.caption;
    const v = $("video", d);
    d.onmouseenter = () => v.play().catch(() => {}); d.onmouseleave = () => v.pause();
    strip.appendChild(d);
  });
}
$("#clearReel").onclick = () => { localStorage.removeItem(REEL_KEY); drawReel(); };
$("#rollAll").onclick = async () => { for (const el of $$("#shots .card")) await roll(el); };
drawReel();
