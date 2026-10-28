"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtDate = (t) => new Date(t * 1000).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
const plural = (n, one, few, many) => {
  const m10 = n % 10, m100 = n % 100;
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
};
const credits = (n) => `${n} ${plural(n, "кредит", "кредита", "кредитов")}`;

function toast(text, ok = false) {
  const t = $("#toast");
  t.textContent = text;
  t.classList.toggle("ok", ok);
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
    if (r.status === 401 && me) {
      me = null;
      applyMe();
      location.hash = "#auth";
    }
    if (r.status === 402 || r.status === 403) refreshMe();
    throw new Error(msg);
  }
  return r;
}
const postJSON = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/* ---------- Аккаунт и тариф ---------- */
let me = null;        // текущий пользователь (null — не вошёл)
let catalog = null;   // тарифы, цены, контакт продавца
let status = null;

async function refreshMe() {
  try {
    me = await (await fetch("/api/me")).json();
    if (!me.login) me = null;
  } catch {
    me = null;
  }
  applyMe();
}

function applyMe() {
  $("#login-btn").hidden = !!me;
  $("#balance").hidden = $("#queue").hidden = !me;
  $("#nav-admin").hidden = !me?.is_admin;
  $("#model-box").hidden = !me?.is_admin;
  if (!me) return;
  $("#balance").innerHTML = `<i style="--p:${me.percent}"></i>${me.percent}%` + (me.bonus ? ` <small>+${me.bonus}</small>` : "");
  const L = me.limits;
  const img = $("#image-form");
  img.width.max = img.height.max = L.max_image_side;
  img.count.max = L.max_images;
  updateImageCost();
  const v = $("#video-form");
  v.seconds.max = Math.max(1, L.video_max_seconds);
  if (+v.seconds.value > L.video_max_seconds) v.seconds.value = Math.max(1, L.video_max_seconds);
  updateVideoHint();
  const vl = $("#video-locked");
  vl.hidden = L.video_max_seconds > 0;
  v.classList.toggle("off", !L.video_max_seconds);
  v.querySelector("button").disabled = !L.video_max_seconds;
  vl.innerHTML = `🔒 Видео недоступно в тарифе «${esc(me.plan_name)}». <a href="#cabinet">Подключите тариф Старт или Про</a>.`;
  applyEffortLimits();
  $("#zip-text").textContent = L.zip ? "Перетащите ZIP проекта или нажмите" : "🔒 ZIP — в платных тарифах";
  $("#zip-drop").classList.toggle("disabled", !L.zip);
  renderCabinet();
}

async function loadCatalog() {
  catalog = await (await api("/api/plans")).json();
  const html = catalog.plans
    .map((p) => `<div class="plan ${p.id === "free" ? "" : "paid"}" data-plan="${p.id}">
        <h3>${esc(p.name)}</h3><div class="price">${esc(p.price)}</div>
        <ul>${p.includes.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>
        <div class="plan-foot"></div></div>`)
    .join("");
  $("#plans-home").innerHTML = $("#plans-cabinet").innerHTML = html;
  $$(".contact").forEach((el) => (el.textContent = "Как купить код: " + catalog.contact));
  const c = catalog.costs;
  $("#cab-costs").textContent = `Цены: фото — ${credits(c.image)}, 1 сек видео — ${credits(c.video_second)}, сообщение в «Код» — ${credits(c.chat)}.`;
  $("#code-plan").innerHTML = catalog.plans.filter((p) => p.id !== "free").map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  applyMe();
}
$("#to-plans").addEventListener("click", () => $("#plans").scrollIntoView({ behavior: "smooth" }));

/* ---------- Навигация ---------- */
const views = ["home", "auth", "image", "video", "code", "tables", "gallery", "cabinet", "admin"];
const needLogin = ["image", "video", "code", "tables", "gallery", "cabinet", "admin"];
function route() {
  let name = views.includes(location.hash.slice(1)) ? location.hash.slice(1) : "home";
  if (needLogin.includes(name) && !me) {
    sessionStorage.setItem("after-login", name);
    name = "auth";
  }
  if (name === "admin" && !me?.is_admin) name = "home";
  if (name === "auth" && me) name = "cabinet";
  views.forEach((v) => ($("#view-" + v).hidden = v !== name));
  $$("nav a").forEach((a) => a.classList.toggle("active", a.hash === "#" + name));
  if (name === "gallery") loadGallery();
  if (name === "cabinet") refreshMe();
  if (name === "admin") loadAdmin();
  if (name === "tables") loadSheets();
  if (name === "code") warmup();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

/* ---------- Вход и регистрация ---------- */
let authMode = "login";
$$("[data-auth]").forEach((b) =>
  b.addEventListener("click", () => {
    authMode = b.dataset.auth;
    $$("[data-auth]").forEach((x) => x.classList.toggle("on", x === b));
    $("#auth-submit").textContent = authMode === "login" ? "Войти" : "Зарегистрироваться";
    $("#auth-form").password.autocomplete = authMode === "login" ? "current-password" : "new-password";
    $("#auth-hint").textContent = authMode === "login"
      ? "Нет аккаунта? Нажмите «Регистрация» — бесплатный тариф подключится сразу."
      : "Укажите email (или логин 3–32 символа) и пароль от 6 символов.";
  }),
);
$("#auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    await postJSON("/api/" + authMode, { login: f.login.value, password: f.password.value });
    f.password.value = "";
    await refreshMe();
    toast(authMode === "login" ? "С возвращением!" : "Аккаунт создан, бесплатный тариф подключён", true);
    location.hash = "#" + (sessionStorage.getItem("after-login") || "cabinet");
    sessionStorage.removeItem("after-login");
    route();
    loadStatus();
  } catch (err) {
    toast(err.message);
  }
});
$("#logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  me = null;
  applyMe();
  location.hash = "#home";
});

/* ---------- Личный кабинет ---------- */
function renderCabinet() {
  if (!me) return;
  $("#cab-login").textContent = me.login;
  $("#cab-plan").textContent = "Тариф: " + me.plan_name;
  $("#ring").style.setProperty("--p", me.percent);
  $("#ring-pct").textContent = me.percent + "%";
  $("#cab-credits").innerHTML =
    `<b>${me.credits}</b> из ${credits(me.quota)} тарифа` + (me.bonus ? ` · <b>+${me.bonus}</b> бонусных (не сгорают)` : "");
  $("#cab-when").textContent = me.days_left != null
    ? `Действует до ${fmtDate(me.plan_until)} — ещё ${me.days_left} ${plural(me.days_left, "день", "дня", "дней")}`
    : me.resets_in_h != null ? `Кредиты обновятся через ${me.resets_in_h} ${plural(me.resets_in_h, "час", "часа", "часов")}` : "";
  $$(".plan").forEach((el) => {
    const cur = el.dataset.plan === me.plan;
    el.classList.toggle("current", cur);
    el.querySelector(".plan-foot").textContent = cur ? "✓ Ваш тариф" : "";
  });
  if (me.usage) {
    $("#usage").innerHTML = me.usage.length
      ? `<tr><th>Когда</th><th>Действие</th><th>Кредиты</th></tr>` +
        me.usage.map((u) => `<tr><td>${fmtDate(u.created)}</td><td>${esc(u.action)}</td><td class="${u.cost < 0 ? "plus" : ""}">${u.cost ? (u.cost < 0 ? "+" + -u.cost : "−" + u.cost) : ""}</td></tr>`).join("")
      : `<tr><td class="hint">Пока пусто</td></tr>`;
  }
}

$("#redeem-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const d = await (await postJSON("/api/redeem", { code: e.target.code.value })).json();
    e.target.code.value = "";
    toast("✓ " + d.message, true);
    await refreshMe();
  } catch (err) {
    toast(err.message);
  }
});

/* ---------- Статус моделей ---------- */
async function loadStatus() {
  if (!me) return;
  try {
    status = await (await api("/api/status")).json();
  } catch {
    return;
  }
  $("#image-form").steps.value = status.image.steps;
  $("#video-form").steps.value = status.video.steps;
  renderEfforts();
  // Движок: локальная модель + подключённые внешние нейросети (DeepSeek, Kimi, ChatGPT).
  const ext = (status.providers || []).map((p) => `<option value="${p.id}">${esc(p.label)} — ${credits(p.cost)}</option>`).join("");
  $("#engine").innerHTML = `<option value="local">Локальная (на вашем ПК)</option>` + ext;
  $("#engine").value = engine;
  $("#model").innerHTML =
    `<option value="">Авто — по уровню</option>` + status.models.map((m) => `<option>${esc(m)}</option>`).join("");
  applyEngine();
}

// Кнопки уровней усилий строятся из ответа сервера (их названия и цена — в config.yaml).
function renderEfforts() {
  if (!status?.efforts) return;
  $("#efforts").innerHTML = Object.entries(status.efforts)
    .map(([id, e]) => `<button type="button" data-effort="${id}" class="${id === effort ? "on" : ""}">
        <b>${esc(e.label)}</b><small>${credits(e.cost)}</small></button>`)
    .join("");
  $$("[data-effort]").forEach((b) => b.addEventListener("click", () => setEffort(b.dataset.effort)));
  applyEffortLimits();
}

// Уровень доступен, если его модель (fast/precise) входит в тариф пользователя.
function applyEffortLimits() {
  if (!status?.efforts || !me) return;
  const allowed = me.limits.chat_modes;
  let cur = status.efforts[effort];
  $$("[data-effort]").forEach((b) => {
    const e = status.efforts[b.dataset.effort];
    const ok = allowed.includes(e.use);
    b.disabled = !ok;
    b.title = ok ? "" : "Доступно в платных тарифах";
  });
  if (cur && !allowed.includes(cur.use)) {
    const first = Object.keys(status.efforts).find((id) => allowed.includes(status.efforts[id].use));
    if (first) setEffort(first);
  }
  cur = status.efforts[effort];
  if (cur) $("#chat-cost").textContent = `Стоимость сообщения: ${credits(cur.cost)}` + ($("#explain").checked ? " · с объяснением" : "");
  applyEngine();
}

// Выбор внешней нейросети. Внешние доступны только на платных тарифах.
let engine = "local";
try { engine = localStorage.getItem("engine") || "local"; } catch {}
function applyEngine() {
  if (!me) return;
  const sel = $("#engine");
  const external = engine !== "local";
  if (external && !me.limits.external) {
    engine = "local";
    sel.value = "local";
  }
  // Для внешней модели цена берётся из её пункта; уровень влияет только на длину.
  const prov = (status?.providers || []).find((p) => p.id === engine);
  if (prov) $("#chat-cost").textContent = `Стоимость сообщения: ${credits(prov.cost)} (${esc(prov.label)})`;
  $("#efforts").classList.toggle("dim", external);
  if (!me.limits.external) {
    sel.title = "Внешние нейросети — в платных тарифах";
  } else {
    sel.title = "";
  }
}
$("#engine").addEventListener("change", (e) => {
  engine = e.target.value;
  try { localStorage.setItem("engine", engine); } catch {}
  applyEngine();
  if (engine === "local") warmup();
});

setInterval(async () => {
  if (!me) return;
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
    box.innerHTML = `⚠️ Ошибка: ${esc(job.error)}. Кредиты возвращены.`;
    return;
  }
  const pct = Math.round(job.progress * 100);
  const known = job.progress > 0 && job.status !== "done";
  const elapsed = job.started ? Math.round(Date.now() / 1000 - job.started) : 0;
  box.innerHTML =
    `<div>${esc(job.desc)} ${known ? pct + "%" : ""} <span class="hint">${elapsed ? "· " + fmtTime(elapsed) : ""}</span></div>` +
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
    if (job.status === "error") {
      refreshMe();
      throw new Error(job.error);
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
}

function formData(form) {
  const d = Object.fromEntries(new FormData(form));
  for (const k of ["width", "height", "steps", "count", "seed"]) if (k in d) d[k] = parseInt(d[k], 10);
  if ("seconds" in d) d.seconds = parseFloat(d.seconds);
  if ("strength" in d) d.strength = parseInt(d.strength, 10) / 100;
  return d;
}

async function uploadImage(file) {
  const fd = new FormData();
  fd.append("file", file);
  return (await (await api("/api/upload-image", { method: "POST", body: fd })).json()).name;
}

function dropZone(zone, onFile) {
  zone.addEventListener("dragover", (e) => (e.preventDefault(), zone.classList.add("over")));
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("over");
    if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0]);
  });
  zone.querySelector("input[type=file]").addEventListener("change", (e) => e.target.files[0] && onFile(e.target.files[0]));
}

/* ---------- Фото: по описанию или по примеру ---------- */
let imageMode = "text";
let refImage = null;
$$("[data-imode]").forEach((b) =>
  b.addEventListener("click", () => {
    imageMode = b.dataset.imode;
    $$("[data-imode]").forEach((x) => x.classList.toggle("on", x === b));
    $("#ref-box").hidden = imageMode !== "ref";
    $("#image-form").prompt.placeholder = imageMode === "ref"
      ? "Что изменить: «в стиле аниме», «сделай зимний пейзаж», «добавь закат»"
      : "Неоновый город ночью под дождём, кинематографично";
  }),
);
$("#image-form").strength.addEventListener("input", (e) => ($("#strength-label").textContent = e.target.value + "%"));
dropZone($("#ref-drop"), async (file) => {
  try {
    refImage = await uploadImage(file);
    $("#ref-preview").src = URL.createObjectURL(file);
    $("#ref-preview").hidden = false;
    $("#ref-text").textContent = "Пример загружен (нажмите, чтобы заменить)";
  } catch (err) {
    toast(err.message);
  }
});

function updateImageCost() {
  if (!catalog || !me) return;
  const n = +$("#image-form").count.value || 1;
  $("#image-cost").textContent =
    `Стоимость: ${credits(n * catalog.costs.image)} · ваш тариф: до ${me.limits.max_image_side} px, до ${me.limits.max_images} шт.`;
}
$("#image-form").count.addEventListener("input", updateImageCost);

$("#image-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (imageMode === "ref" && !refImage) return toast("Сначала загрузите пример фото");
  const btn = e.target.querySelector("button:not([type=button])");
  btn.disabled = true;
  const box = $("#image-job");
  try {
    const data = formData(e.target);
    data.ref_image = imageMode === "ref" ? refImage : null;
    const job = await (await postJSON("/api/image", data)).json();
    refreshMe();
    renderJob(box, job);
    const done = await waitJob(job.id, box);
    $("#image-result").innerHTML = done.result
      .map((u) => `<figure><img src="${u}" alt=""><a class="dl" href="${u}" download>⬇ Скачать</a></figure>`)
      .join("");
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
  const cost = catalog ? ` Стоимость: ${credits(Math.ceil(s) * catalog.costs.video_second)}.` : "";
  $("#video-hint").textContent =
    `~${Math.max(1, Math.ceil(s / 5))} сегм. по 5 сек.${cost} ` + (s > 30 ? "Длинное видео может генерироваться час и больше." : "");
}
secInput.addEventListener("input", updateVideoHint);

dropZone($("#start-drop"), async (file) => {
  try {
    startImage = await uploadImage(file);
    $("#start-preview").src = URL.createObjectURL(file);
    $("#start-preview").hidden = false;
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
    refreshMe();
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

dropZone($("#zip-drop"), async (file) => {
  if (!me?.limits.zip) return toast("Загрузка ZIP доступна в платных тарифах");
  const fd = new FormData();
  fd.append("file", file);
  $("#zip-text").textContent = "Распаковка…";
  try {
    const d = await (await api("/api/zip", { method: "POST", body: fd })).json();
    projectId = d.project_id;
    warmup();
    $("#zip-text").textContent = "📦 " + d.name + " — загружен";
    $("#zip-tree").textContent = d.tree;
    $("#zip-tree").hidden = false;
  } catch (err) {
    $("#zip-text").textContent = "Перетащите ZIP проекта или нажмите";
    toast(err.message);
  }
});

function renderMarkdown(text) {
  const parts = text.split(/```([^\n`]*)\n?([\s\S]*?)(?:```|$)/g);
  let html = "";
  for (let i = 0; i < parts.length; i += 3) {
    if (parts[i].trim()) {
      html += "<p>" + esc(parts[i].trim()).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>") + "</p>";
    }
    if (i + 2 < parts.length) {
      const header = parts[i + 1].trim();
      // Заголовок блока вида "python app/main.py" — имя файла для скачивания артефакта.
      const name = header.split(/\s+/).find((w) => w.includes(".") || w.includes("/"));
      const file = name ? name.replace(/^\//, "").replace(/\.\./g, "_") : `code.${header.split(/\s+/)[0] || "txt"}`;
      html += `<pre><span class="lang">${esc(header)}</span>` +
        `<span class="pre-btns"><button type="button" data-dl="${esc(file)}" title="Скачать файл">⬇</button>` +
        `<button type="button" data-copy>Копировать</button></span>` +
        `<code>${esc(parts[i + 2])}</code></pre>`;
    }
  }
  return html;
}

const msgHTML = (m) =>
  m.role === "user"
    ? esc(m.content)
    : renderMarkdown(m.content || "…") + (m.stats ? `<div class="speed">${esc(m.stats)}</div>` : "");

function renderChat() {
  const box = $("#messages");
  if (!history.length) {
    box.innerHTML = `<p class="empty">Опишите задачу: «Напиши сайт-визитку», «Найди ошибку в моём проекте»…</p>`;
    return;
  }
  box.innerHTML = history.map((m) => `<div class="msg ${m.role}">${msgHTML(m)}</div>`).join("");
  box.scrollTop = box.scrollHeight;
}

// Во время ответа перерисовываем только последнее сообщение и не чаще одного раза
// за кадр экрана — так длинный чат не тормозит, а текст появляется плавно.
let drawPending = false;
function drawLast() {
  if (drawPending) return;
  drawPending = true;
  requestAnimationFrame(() => {
    drawPending = false;
    const box = $("#messages");
    const el = box.lastElementChild;
    if (!el) return;
    const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    el.innerHTML = msgHTML(history[history.length - 1]);
    if (stick) box.scrollTop = box.scrollHeight;
  });
}

// Код из ответа можно скачать: одним файлом (артефактом) или всё сразу (ZIP).
$("#messages").addEventListener("click", (e) => {
  const pre = e.target.closest("pre");
  if (e.target.matches("[data-copy]")) {
    navigator.clipboard.writeText(pre.querySelector("code").textContent);
    e.target.textContent = "Скопировано";
  } else if (e.target.matches("[data-dl]")) {
    const blob = new Blob([pre.querySelector("code").textContent], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = e.target.dataset.dl || "file.txt";
    a.click();
  }
});

/* Уровень усилий: low / medium / high (из config.yaml). Чем выше — дороже. */
let effort = "medium";
try { effort = localStorage.getItem("effort") || "medium"; } catch {}
function setEffort(id) {
  effort = id;
  try { localStorage.setItem("effort", id); } catch {}
  $$("[data-effort]").forEach((b) => b.classList.toggle("on", b.dataset.effort === id));
  applyEffortLimits();
  warmup();
}
$("#explain").addEventListener("change", applyEffortLimits);

// Просим сервер заранее загрузить модель, чтобы ответ начался без ожидания.
function warmup() {
  if (location.hash !== "#code" || !me || engine !== "local") return;  // внешним моделям прогрев не нужен
  postJSON("/api/warmup", { effort, model: $("#model").value || null, project_id: projectId }).catch(() => {});
}
$("#model").addEventListener("change", warmup);

/* Голосовой ввод (распознавание речи в браузере) */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recog = null;
if (SR) {
  $("#mic").addEventListener("click", () => {
    if (recog) {
      recog.stop();
      return;
    }
    recog = new SR();
    recog.lang = "ru-RU";
    recog.interimResults = true;
    const base = $("#chat-input").value;
    recog.onresult = (e) => {
      const text = Array.from(e.results).map((r) => r[0].transcript).join("");
      $("#chat-input").value = (base ? base + " " : "") + text;
    };
    recog.onend = () => {
      $("#mic").classList.remove("on");
      recog = null;
    };
    recog.onerror = () => toast("Не удалось распознать речь. Разрешите доступ к микрофону.");
    recog.start();
    $("#mic").classList.add("on");
  });
} else {
  $("#mic").hidden = true;
}

let sending = false;
async function sendChat() {
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text || sending) return;
  sending = true;
  input.value = "";
  history.push({ role: "user", content: text });
  const answer = { role: "assistant", content: "" };
  const req = { messages: history.slice(), effort, engine, explain: $("#explain").checked,
                model: $("#model").value || null, project_id: projectId };
  history.push(answer);
  renderChat();
  const t0 = performance.now();
  let firstWord = 0;
  let tail = "";
  try {
    const r = await postJSON("/api/chat", req);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      tail += dec.decode(value, { stream: true });
      const cut = tail.indexOf("\u0000");  // дальше — статистика скорости от сервера
      answer.content = cut < 0 ? tail : tail.slice(0, cut);
      if (!firstWord && answer.content.trim()) firstWord = (performance.now() - t0) / 1000;
      drawLast();
    }
    const cut = tail.indexOf("\u0000");
    if (cut >= 0) {
      const st = JSON.parse(tail.slice(cut + 1));
      answer.stats =
        `⚡ ${st.tok_per_s} ток/с · первые слова через ${firstWord.toFixed(1)} с · всего ${st.total_s} с · ${st.model}` +
        (st.load_s > 1 ? ` · загрузка модели ${st.load_s} с` : "");
    }
  } catch (err) {
    answer.content += "\n⚠️ " + err.message;
  } finally {
    sending = false;
    drawLast();
    refreshMe();
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
      ? items.map((it) => (it.type === "video"
          ? `<video src="${it.url}" muted loop playsinline preload="metadata" title="${esc(it.prompt)}"></video>`
          : `<img src="${it.url}" loading="lazy" alt="" title="${esc(it.prompt)}">`)).join("")
      : `<p class="empty">Пока пусто — создайте первое фото или видео</p>`;
  } catch (err) {
    toast(err.message);
  }
}

/* ---------- Админ-панель ---------- */
let codeKind = "plan";
$$("[data-ckind]").forEach((b) =>
  b.addEventListener("click", () => {
    codeKind = b.dataset.ckind;
    $$("[data-ckind]").forEach((x) => x.classList.toggle("on", x === b));
    $("#ck-plan").hidden = codeKind !== "plan";
    $("#ck-credits-hint").textContent = codeKind === "plan" ? "(пусто — как в тарифе)" : "(обязательно)";
  }),
);

$("#codes-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const num = (v) => (v ? parseInt(v, 10) : null);
  try {
    const d = await (await postJSON("/api/admin/codes", {
      kind: codeKind, plan: codeKind === "plan" ? f.plan.value : null, days: num(f.days.value),
      credits: num(f.credits.value), count: num(f.count.value) || 1, note: f.note.value,
    })).json();
    $("#new-codes").value = d.codes.join("\n");
    toast(`Создано кодов: ${d.codes.length}`, true);
    loadAdmin();
  } catch (err) {
    toast(err.message);
  }
});
$("#copy-codes").addEventListener("click", () => {
  navigator.clipboard.writeText($("#new-codes").value);
  toast("Коды скопированы", true);
});

async function loadAdmin() {
  try {
    const [codes, users] = await Promise.all([
      api("/api/admin/codes").then((r) => r.json()),
      api("/api/admin/users").then((r) => r.json()),
    ]);
    const planName = (id) => catalog?.plans.find((p) => p.id === id)?.name || id;
    $("#codes-table").innerHTML = codes.length
      ? `<tr><th>Код</th><th>Что даёт</th><th>Статус</th><th>Заметка</th><th>Создан</th></tr>` +
        codes.map((c) => `<tr><td class="mono">${c.code}</td>
          <td>${c.kind === "plan" ? `${esc(planName(c.plan))}, ${c.days} дн., ${c.credits} кр.` : `Пакет: ${c.credits} кр.`}</td>
          <td>${c.used_by ? `<span class="tag used">${esc(c.used_login)} · ${fmtDate(c.used_at)}</span>` : `<span class="tag free">свободен</span>`}</td>
          <td>${esc(c.note)}</td><td>${fmtDate(c.created)}</td></tr>`).join("")
      : `<tr><td class="hint">Кодов пока нет</td></tr>`;
    $("#users-table").innerHTML =
      `<tr><th>Логин</th><th>Тариф</th><th>Осталось</th><th>Бонус</th><th>До</th><th>Регистрация</th></tr>` +
      users.map((u) => `<tr><td>${esc(u.login)}${u.is_admin ? " 👑" : ""}</td><td>${esc(u.plan_name)}</td>
        <td>${u.percent}% (${u.credits}/${u.quota})</td><td>${u.bonus}</td>
        <td>${u.plan_until ? fmtDate(u.plan_until) : "—"}</td><td>${fmtDate(u.created)}</td></tr>`).join("");
    loadPricing();
  } catch (err) {
    toast(err.message);
  }
}

/* ---------- Админ: цены ---------- */
async function loadPricing() {
  const p = await (await api("/api/admin/pricing")).json();
  const f = $("#pricing-form");
  f.image.value = p.costs.image;
  f.video_second.value = p.costs.video_second;
  f.chat.value = p.costs.chat;
  // Цена и кредиты по каждому платному тарифу.
  $("#plan-prices").innerHTML = Object.entries(p.plans)
    .filter(([id]) => id !== "free")
    .map(([id, pl]) => `<div class="price-row"><b>${esc(pl.name)}</b>
        <label>Цена (текст)<input data-price="${id}" value="${esc(pl.price)}"></label>
        <label>Кредитов в тарифе<input data-credits="${id}" type="number" min="0" value="${pl.credits}"></label>
      </div>`)
    .join("");
}
$("#pricing-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const plans = {};
  $$("[data-price]").forEach((i) => (plans[i.dataset.price] = { ...plans[i.dataset.price], price: i.value }));
  $$("[data-credits]").forEach((i) => (plans[i.dataset.credits] = { ...plans[i.dataset.credits], credits: +i.value }));
  try {
    await postJSON("/api/admin/pricing", {
      costs: { image: +f.image.value, video_second: +f.video_second.value, chat: +f.chat.value },
      plans,
    });
    toast("Цены сохранены — их уже видят все", true);
    loadCatalog();            // обновляем тарифы на сайте
    if (me) loadStatus();
  } catch (err) {
    toast(err.message);
  }
});

/* ---------- Таблицы с автоподсчётом ---------- */
let sheet = null;             // открытая таблица {id, name, rows, cols, data}
let sheetSaveTimer = null;

async function loadSheets() {
  try {
    const list = await (await api("/api/sheets")).json();
    $("#sheet-list").innerHTML = list.length
      ? list.map((s) => `<button type="button" class="sheet-item ${sheet && sheet.id === s.id ? "on" : ""}" data-sheet="${s.id}">${esc(s.name)}</button>`).join("")
      : `<p class="hint">Таблиц пока нет</p>`;
    $$("[data-sheet]").forEach((b) => b.addEventListener("click", () => openSheet(+b.dataset.sheet)));
  } catch (err) {
    toast(err.message);
  }
}

$("#new-sheet").addEventListener("click", async () => {
  try {
    const s = await (await postJSON("/api/sheets", { name: "Таблица", rows: 10, cols: 6 })).json();
    await loadSheets();
    openSheet(s.id);
  } catch (err) {
    toast(err.message);
  }
});

async function openSheet(id) {
  sheet = await (await api("/api/sheets/" + id)).json();
  $("#sheet-empty").hidden = true;
  $("#sheet-head").hidden = false;
  $("#sheet-name").value = sheet.name;
  $$("[data-sheet]").forEach((b) => b.classList.toggle("on", +b.dataset.sheet === id));
  renderSheet();
}

const colName = (n) => {            // 0->A, 25->Z, 26->AA …
  let s = "";
  n += 1;
  while (n > 0) {
    s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
};

function renderSheet() {
  if (!sheet) return;
  const vals = computeSheet(sheet.data);
  let html = "<tr><th></th>";
  for (let c = 0; c < sheet.cols; c++) html += `<th>${colName(c)}</th>`;
  html += "</tr>";
  for (let r = 0; r < sheet.rows; r++) {
    html += `<tr><th>${r + 1}</th>`;
    for (let c = 0; c < sheet.cols; c++) {
      const raw = sheet.data[r][c] ?? "";
      const shown = vals[r][c];
      html += `<td><input data-r="${r}" data-c="${c}" value="${esc(raw)}" title="${esc(String(shown))}"></td>`;
    }
    html += "</tr>";
  }
  $("#sheet").innerHTML = html;
  // Показываем посчитанный результат, пока ячейка не в фокусе; при фокусе — формулу.
  $$("#sheet input").forEach((inp) => {
    const r = +inp.dataset.r, c = +inp.dataset.c;
    if (document.activeElement !== inp && String(sheet.data[r][c]).startsWith("=")) inp.value = vals[r][c];
    inp.addEventListener("focus", () => (inp.value = sheet.data[r][c] ?? ""));
    inp.addEventListener("blur", () => {
      sheet.data[r][c] = inp.value;
      renderSheet();
      scheduleSheetSave();
    });
  });
}

function scheduleSheetSave() {
  $("#sheet-saved").textContent = "сохранение…";
  clearTimeout(sheetSaveTimer);
  sheetSaveTimer = setTimeout(saveSheet, 700);
}

async function saveSheet() {
  if (!sheet) return;
  try {
    await api("/api/sheets/" + sheet.id, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("#sheet-name").value, rows: sheet.rows, cols: sheet.cols, data: sheet.data }),
    });
    $("#sheet-saved").textContent = "✓ сохранено";
    loadSheets();
  } catch (err) {
    $("#sheet-saved").textContent = "";
    toast(err.message);
  }
}
$("#sheet-name").addEventListener("input", scheduleSheetSave);
$("#add-row").addEventListener("click", () => {
  if (!sheet) return;
  sheet.data.push(new Array(sheet.cols).fill(""));
  sheet.rows++;
  renderSheet();
  scheduleSheetSave();
});
$("#add-col").addEventListener("click", () => {
  if (!sheet) return;
  sheet.data.forEach((row) => row.push(""));
  sheet.cols++;
  renderSheet();
  scheduleSheetSave();
});
$("#del-sheet").addEventListener("click", async () => {
  if (!sheet || !confirm("Удалить эту таблицу?")) return;
  await api("/api/sheets/" + sheet.id, { method: "DELETE" });
  sheet = null;
  $("#sheet-head").hidden = true;
  $("#sheet").innerHTML = "";
  $("#sheet-empty").hidden = false;
  loadSheets();
});

// Разбор арифметики (+ - * / и скобки) без eval — рекурсивный спуск, безопасно при CSP.
function safeArith(src) {
  const s = src.replace(/\s+/g, "");
  let i = 0;
  const factor = () => {
    if (s[i] === "(") { i++; const v = expr(); if (s[i] !== ")") throw 0; i++; return v; }
    if (s[i] === "-") { i++; return -factor(); }
    if (s[i] === "+") { i++; return factor(); }
    const m = /^\d+\.?\d*/.exec(s.slice(i));
    if (!m) throw 0;
    i += m[0].length;
    return parseFloat(m[0]);
  };
  const term = () => {
    let v = factor();
    while (s[i] === "*" || s[i] === "/") { const op = s[i++]; const r = factor(); v = op === "*" ? v * r : v / r; }
    return v;
  };
  function expr() {
    let v = term();
    while (s[i] === "+" || s[i] === "-") { const op = s[i++]; const r = term(); v = op === "+" ? v + r : v - r; }
    return v;
  }
  const v = expr();
  if (i !== s.length) throw 0;
  return v;
}

/* Подсчёт значений ячеек. Формула начинается с "=". Поддержка A1, диапазонов,
   СУММ/СРЗНАЧ/МИН/МАКС/СЧЁТ (и англ. SUM/AVG/MIN/MAX/COUNT), + - * / ( ). */
function computeSheet(data) {
  const rows = data.length, cols = data[0]?.length || 0;
  const cache = {};
  const cell = (r, c) => (r >= 0 && r < rows && c >= 0 && c < cols ? data[r][c] : "");
  const ref = (name) => {
    const m = /^([A-Za-z]+)(\d+)$/.exec(name);
    if (!m) return 0;
    let col = 0;
    for (const ch of m[1].toUpperCase()) col = col * 26 + (ch.charCodeAt(0) - 64);
    return evalCell(+m[2] - 1, col - 1);
  };
  const range = (a, b) => {
    const pa = /^([A-Za-z]+)(\d+)$/.exec(a), pb = /^([A-Za-z]+)(\d+)$/.exec(b);
    if (!pa || !pb) return [];
    const colN = (s) => { let n = 0; for (const ch of s.toUpperCase()) n = n * 26 + (ch.charCodeAt(0) - 64); return n - 1; };
    const [c1, c2] = [colN(pa[1]), colN(pb[1])].sort((x, y) => x - y);
    const [r1, r2] = [+pa[2] - 1, +pb[2] - 1].sort((x, y) => x - y);
    const out = [];
    for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) out.push(evalCell(r, c));
    return out;
  };
  const FUNCS = {
    SUM: (a) => a.reduce((s, x) => s + (+x || 0), 0), СУММ: (a) => FUNCS.SUM(a),
    AVG: (a) => (a.length ? FUNCS.SUM(a) / a.length : 0), СРЗНАЧ: (a) => FUNCS.AVG(a),
    MIN: (a) => Math.min(...a.map(Number)), МИН: (a) => FUNCS.MIN(a),
    MAX: (a) => Math.max(...a.map(Number)), МАКС: (a) => FUNCS.MAX(a),
    COUNT: (a) => a.filter((x) => x !== "" && !isNaN(+x)).length, СЧЁТ: (a) => FUNCS.COUNT(a),
  };
  function evalFormula(expr) {
    // Функции с диапазоном: ИМЯ(A1:B2)
    expr = expr.replace(/([A-Za-zА-Яа-яЁё]+)\(\s*([A-Za-z]+\d+)\s*:\s*([A-Za-z]+\d+)\s*\)/g, (_, fn, a, b) => {
      const f = FUNCS[fn.toUpperCase()];
      return f ? f(range(a, b)) : 0;
    });
    // Ссылки на ячейки A1 -> значение
    expr = expr.replace(/\b([A-Za-z]+\d+)\b/g, (_, n) => {
      const v = ref(n);
      return isNaN(+v) ? 0 : +v;
    });
    if (!/^[-+*/().\s\d]*$/.test(expr)) return "#ОШ";    // только безопасная арифметика
    try {
      const val = safeArith(expr || "0");                // без eval/Function — работает при строгом CSP
      return typeof val === "number" && isFinite(val) ? Math.round(val * 1e6) / 1e6 : "#ОШ";
    } catch {
      return "#ОШ";
    }
  }
  function evalCell(r, c) {
    const key = r + ":" + c;
    if (key in cache) return cache[key];
    cache[key] = "#ЦИКЛ";                 // защита от зацикленных ссылок
    const raw = String(cell(r, c) ?? "");
    const out = raw.startsWith("=") ? evalFormula(raw.slice(1)) : raw;
    cache[key] = out;
    return out;
  }
  return data.map((row, r) => row.map((_, c) => evalCell(r, c)));
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

/* ---------- Установка приложения (PWA) ---------- */
let installPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  $("#install").hidden = false;
});
$("#install").addEventListener("click", async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  $("#install").hidden = true;
});
window.addEventListener("appinstalled", () => ($("#install").hidden = true));
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}

/* ---------- Старт ---------- */
(async () => {
  await refreshMe();
  route();
  loadCatalog().catch(() => {});
  loadStatus();
})();
