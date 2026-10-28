"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function toast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 5000);
}

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const d = (await r.json()).detail;
      msg = Array.isArray(d) ? d.map((e) => e.msg).join("; ") : d;
    } catch {}
    throw new Error(msg);
  }
  return r;
}
const postJSON = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/* ---------- Навигация ---------- */
const views = ["home", "image", "video", "code", "gallery"];
function route() {
  const name = views.includes(location.hash.slice(1)) ? location.hash.slice(1) : "home";
  views.forEach((v) => ($("#view-" + v).hidden = v !== name));
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.hash === "#" + name));
  if (name === "gallery") loadGallery();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

/* ---------- Статус ---------- */
let status = {};
async function loadStatus() {
  try {
    status = await (await api("/api/status")).json();
  } catch {
    $("#status-box").textContent = "Сервер ARTurokAI не отвечает.";
    return;
  }
  const llm = status.models.length
    ? `<b>Ollama:</b> ${status.models.length} моделей установлено`
    : `<b>Ollama:</b> не запущена — для кода установите с ollama.com и выполните <code>ollama pull ${esc(status.default_model)}</code>`;
  $("#status-box").innerHTML =
    `<b>Фото:</b> ${esc(status.image.model)} · <b>Видео:</b> ${esc(status.video.t2v_model)}<br>${llm}`;

  const f = $("#image-form");
  f.width.value = status.image.width;
  f.height.value = status.image.height;
  f.steps.value = status.image.steps;
  const v = $("#video-form");
  v.steps.value = status.video.steps;
  v.seconds.max = status.video.max_seconds;

  const sel = $("#model");
  const models = status.models.length ? status.models : [status.default_model];
  if (!models.includes(status.default_model)) models.unshift(status.default_model);
  sel.innerHTML = models.map((m) => `<option ${m === status.default_model ? "selected" : ""}>${esc(m)}</option>`).join("");
  updateVideoHint();
}

setInterval(async () => {
  try {
    const jobs = await (await api("/api/jobs")).json();
    const active = jobs.filter((j) => j.status === "queued" || j.status === "running").length;
    $("#queue").textContent = "⏳ " + active;
  } catch {}
}, 3000);

/* ---------- Задачи ---------- */
function renderJob(box, job) {
  box.hidden = false;
  box.classList.toggle("error", job.status === "error");
  if (job.status === "error") {
    box.innerHTML = `⚠️ Ошибка: ${esc(job.error || "")}`;
    return;
  }
  const pct = Math.round(job.progress * 100);
  const known = job.progress > 0 && job.status !== "done";
  const elapsed = job.started ? Math.round((Date.now() / 1000 - job.started)) : 0;
  box.innerHTML =
    `<div>${esc(job.desc || "")} ${known ? pct + "%" : ""} <span class="hint">${elapsed ? "· " + fmtTime(elapsed) : ""}</span></div>` +
    `<div class="bar ${known ? "" : "indeterminate"}"><i style="width:${known ? pct : 30}%"></i></div>`;
}
const fmtTime = (s) => (s < 60 ? s + " сек" : Math.floor(s / 60) + " мин " + (s % 60) + " сек");

async function waitJob(id, box) {
  for (;;) {
    const job = await (await api("/api/jobs/" + id)).json();
    if (job.status === "done") {
      box.hidden = true;
      return job;
    }
    renderJob(box, job);
    if (job.status === "error") throw new Error(job.error);
    await new Promise((r) => setTimeout(r, 1500));
  }
}

function formData(form) {
  const d = Object.fromEntries(new FormData(form));
  for (const k of ["width", "height", "steps", "count", "seed"]) if (k in d) d[k] = parseInt(d[k], 10);
  if ("seconds" in d) d.seconds = parseFloat(d.seconds);
  return d;
}

/* ---------- Фото ---------- */
$("#image-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  const box = $("#image-job");
  try {
    const job = await (await postJSON("/api/image", formData(e.target))).json();
    renderJob(box, job);
    const done = await waitJob(job.id, box);
    $("#image-result").innerHTML = done.result.map((u) => `<a href="${u}" download><img src="${u}" alt=""></a>`).join("");
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
});

/* ---------- Видео ---------- */
let startImage = null;
const secInput = $("#video-form").seconds;
function updateVideoHint() {
  const s = +secInput.value;
  $("#sec-label").textContent = s >= 60 ? `${Math.floor(s / 60)} мин ${s % 60 ? (s % 60) + " сек" : ""}` : s + " сек";
  const segs = Math.max(1, Math.ceil(s / 5));
  $("#video-hint").textContent =
    `Будет создано ~${segs} сегм. по 5 сек. ` + (s > 30 ? "Длинное видео может генерироваться час и больше." : "");
}
secInput.addEventListener("input", updateVideoHint);

$("#start-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    startImage = (await (await api("/api/upload-image", { method: "POST", body: fd })).json()).name;
    const img = $("#start-preview");
    img.src = URL.createObjectURL(file);
    img.hidden = false;
    $("#start-text").textContent = "Стартовый кадр выбран (нажмите, чтобы заменить)";
  } catch (err) {
    toast(err.message);
  }
});

$("#video-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  const box = $("#video-job");
  try {
    const job = await (await postJSON("/api/video", { ...formData(e.target), start_image: startImage })).json();
    renderJob(box, job);
    const done = await waitJob(job.id, box);
    const u = done.result[0];
    $("#video-result").innerHTML = `<video src="${u}" controls autoplay loop></video><a class="dl" href="${u}" download>⬇ Скачать MP4</a>`;
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
});

/* ---------- Код и ZIP ---------- */
let projectId = null;
let history = [];

async function uploadZip(file) {
  const fd = new FormData();
  fd.append("file", file);
  $("#zip-text").textContent = "Распаковка…";
  try {
    const d = await (await api("/api/zip", { method: "POST", body: fd })).json();
    projectId = d.project_id;
    $("#zip-text").textContent = "📦 " + d.name + " — загружен";
    $("#zip-tree").textContent = d.tree;
    $("#zip-tree").hidden = false;
  } catch (err) {
    $("#zip-text").textContent = "Перетащите ZIP проекта или нажмите";
    toast(err.message);
  }
}
$("#zip-file").addEventListener("change", (e) => e.target.files[0] && uploadZip(e.target.files[0]));
const drop = $("#zip-drop");
drop.addEventListener("dragover", (e) => (e.preventDefault(), drop.classList.add("over")));
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  if (e.dataTransfer.files[0]) uploadZip(e.dataTransfer.files[0]);
});

function renderMarkdown(text) {
  const parts = text.split(/```([^\n`]*)\n?([\s\S]*?)(?:```|$)/g);
  let html = "";
  for (let i = 0; i < parts.length; i += 3) {
    if (parts[i].trim()) {
      html += "<p>" + esc(parts[i].trim()).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>") + "</p>";
    }
    if (i + 2 < parts.length) {
      html += `<pre><span class="lang">${esc(parts[i + 1])}</span><button type="button" data-copy>Копировать</button><code>${esc(parts[i + 2])}</code></pre>`;
    }
  }
  return html;
}

function renderChat() {
  const box = $("#messages");
  if (!history.length) {
    box.innerHTML = `<p class="empty">Опишите задачу: «Напиши сайт-визитку», «Найди ошибку в моём проекте»…</p>`;
    return;
  }
  box.innerHTML = history
    .map((m) => `<div class="msg ${m.role}">${m.role === "user" ? esc(m.content) : renderMarkdown(m.content || "…")}</div>`)
    .join("");
  box.scrollTop = box.scrollHeight;
}

$("#messages").addEventListener("click", (e) => {
  if (!e.target.matches("[data-copy]")) return;
  navigator.clipboard.writeText(e.target.parentElement.querySelector("code").textContent);
  e.target.textContent = "Скопировано";
});

let sending = false;
async function sendChat() {
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text || sending) return;
  sending = true;
  input.value = "";
  history.push({ role: "user", content: text });
  const answer = { role: "assistant", content: "" };
  const req = { messages: history.slice(), model: $("#model").value, project_id: projectId };
  history.push(answer);
  renderChat();
  try {
    const r = await postJSON("/api/chat", req);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      answer.content += dec.decode(value, { stream: true });
      renderChat();
    }
  } catch (err) {
    answer.content += "\n⚠️ " + err.message;
    renderChat();
  } finally {
    sending = false;
  }
}
$("#chat-form").addEventListener("submit", (e) => (e.preventDefault(), sendChat()));
$("#chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
});
$("#clear").addEventListener("click", () => ((history = []), renderChat()));

$("#export").addEventListener("click", async () => {
  const text = history.filter((m) => m.role === "assistant").map((m) => m.content).join("\n");
  try {
    const blob = await (await postJSON("/api/export", { text })).blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "arturokai_code.zip";
    a.click();
  } catch (err) {
    toast(err.message);
  }
});

/* ---------- Галерея ---------- */
async function loadGallery() {
  try {
    const items = await (await api("/api/gallery")).json();
    $("#gallery").innerHTML = items.length
      ? items.map((it) => (it.type === "video" ? `<video src="${it.url}" muted loop playsinline preload="metadata"></video>` : `<img src="${it.url}" loading="lazy" alt="">`)).join("")
      : `<p class="empty">Пока пусто — создайте первое фото или видео</p>`;
  } catch (err) {
    toast(err.message);
  }
}

/* ---------- Просмотр на весь экран ---------- */
document.addEventListener("click", (e) => {
  const el = e.target;
  if (el.closest("#lightbox")) return ($("#lightbox").hidden = true);
  if (!el.closest(".grid") || !el.matches("img, video")) return;
  e.preventDefault();
  const lb = $("#lightbox");
  lb.innerHTML = el.tagName === "IMG" ? `<img src="${el.src}" alt="">` : `<video src="${el.src}" controls autoplay loop></video>`;
  lb.hidden = false;
});
document.addEventListener("mouseover", (e) => e.target.matches("#gallery video") && e.target.play());
document.addEventListener("mouseout", (e) => e.target.matches("#gallery video") && e.target.pause());

route();
loadStatus();
