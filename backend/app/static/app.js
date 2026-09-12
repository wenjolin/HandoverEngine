const RECENT_KEY = "handover_recent";
const LEGACY_KEY = "handover_plan_id";
const MAX_RECENT = 20;
const ST_LABEL = {
  unread: "未讀",
  reading: "上手中",
  passed: "已通過",
  failed: "未通過",
};
const VIEW_TITLES = {
  home: "選擇交接項目，開始上手",
  learn: "每日任務",
  gaps: "交接缺口",
};

const form = document.getElementById("form");
const submitBtn = document.getElementById("submit");
const badge = document.getElementById("badge");
const jobLabel = document.getElementById("jobLabel");
const pageTitle = document.getElementById("pageTitle");
const messageEl = document.getElementById("message");
const errorEl = document.getElementById("error");
const jobBar = document.getElementById("jobBar");
const dayList = document.getElementById("dayList");
const dayEmpty = document.getElementById("dayEmpty");
const dayView = document.getElementById("dayView");
const courseCards = document.getElementById("courseCards");
const courseEmpty = document.getElementById("courseEmpty");
const btnMid = document.getElementById("btnMid");
const btnFinal = document.getElementById("btnFinal");
const recentList = document.getElementById("recentList");
const recentEmpty = document.getElementById("recentEmpty");
const recentError = document.getElementById("recentError");
const btnClearAll = document.getElementById("btnClearAll");
const dateChip = document.getElementById("dateChip");
const greetKicker = document.getElementById("greetKicker");
const assistantForm = document.getElementById("assistantForm");
const assistantQ = document.getElementById("assistantQ");
const assistantSend = document.getElementById("assistantSend");
const assistantLog = document.getElementById("assistantLog");
const assistantError = document.getElementById("assistantError");
const navHome = document.getElementById("navHome");
const navLearn = document.getElementById("navLearn");
const navGaps = document.getElementById("navGaps");
const btnNewUpload = document.getElementById("btnNewUpload");
const uploadPanel = document.getElementById("uploadPanel");
const chatPanel = document.getElementById("chatPanel");
const btnFabChat = document.getElementById("btnFabChat");
const btnCloseChat = document.getElementById("btnCloseChat");
const shell = document.getElementById("shell");
const btnToggleSidebar = document.getElementById("btnToggleSidebar");
const gapsList = document.getElementById("gapsList");
const gapsEmpty = document.getElementById("gapsEmpty");
const gapsSummary = document.getElementById("gapsSummary");
const btnExportGaps = document.getElementById("btnExportGaps");
const btnToggleGapSelection = document.getElementById("btnToggleGapSelection");

const VIEWS = {
  home: document.getElementById("viewHome"),
  learn: document.getElementById("viewLearn"),
  gaps: document.getElementById("viewGaps"),
};

const SIDEBAR_KEY = "handover_sidebar_collapsed";

let timer = null;
let planId = null;
let planData = null;
let currentDay = 1;
let pendingMeta = null;
let currentView = "home";
let gapSelectionMode = false;
let selectedGapIds = new Set();
let draggedGapId = null;

function fmtDetail(detail) {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  try { return JSON.stringify(detail); } catch { return String(detail); }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
}

function setBadge(status) {
  badge.textContent = status;
  badge.className = "badge";
  if (status === "done") badge.classList.add("done");
  else if (status === "failed") badge.classList.add("failed");
  else if (status !== "idle") badge.classList.add("run");
}

function setPlanNavEnabled(on) {
  navLearn.disabled = !on;
  navGaps.disabled = !on;
}

function showView(name) {
  if (!VIEWS[name]) return;
  if ((name === "learn" || name === "gaps") && !planId) {
    recentError.textContent = "請先從交接首頁開啟一個交接項目";
    name = "home";
  }
  currentView = name;
  Object.entries(VIEWS).forEach(([key, el]) => {
    el.classList.toggle("hidden", key !== name);
  });
  document.querySelectorAll(".nav-item[data-view]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === name);
  });
  pageTitle.textContent = VIEW_TITLES[name] || "接棒引擎";
  btnNewUpload.classList.toggle("hidden", name !== "home");
  if (name !== "home") {
    uploadPanel.classList.add("hidden");
    btnNewUpload.textContent = "新增分析";
  }
  if (name === "gaps" && planId) loadGaps(planId);
}

function applySidebarCollapsed(collapsed) {
  shell.classList.toggle("sidebar-collapsed", collapsed);
  btnToggleSidebar.setAttribute("aria-label", collapsed ? "展開側邊欄" : "收起側邊欄");
  try { localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0"); } catch (_) {}
}

function openChatPanel() {
  chatPanel.classList.remove("hidden");
  setTimeout(() => assistantQ.focus(), 50);
}

function closeChatPanel() {
  chatPanel.classList.add("hidden");
}

function toggleChatPanel() {
  if (chatPanel.classList.contains("hidden")) openChatPanel();
  else closeChatPanel();
}

function openUploadPanel() {
  showView("home");
  uploadPanel.classList.remove("hidden");
  btnNewUpload.textContent = "收起上傳";
  const file = document.getElementById("file");
  if (file) setTimeout(() => file.focus(), 50);
  uploadPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function closeUploadPanel() {
  uploadPanel.classList.add("hidden");
  btnNewUpload.textContent = "新增分析";
}

function loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch (_) {
    return [];
  }
}

function saveRecent(list) {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, MAX_RECENT))); } catch (_) {}
}

function formatDateLabel(iso) {
  const d = iso ? new Date(iso) : new Date();
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function displayTitle(item) {
  const name = item.name || "未命名.zip";
  const date = formatDateLabel(item.done_at);
  const days = item.days != null ? `${item.days}天` : "";
  return [name, date, days].filter(Boolean).join(" · ");
}

function findRecent(id) {
  return loadRecent().find((x) => x.job_id === id) || null;
}

function upsertRecent(entry) {
  const list = loadRecent().filter((x) => x.job_id !== entry.job_id);
  list.unshift(entry);
  saveRecent(list);
  renderRecent();
  renderCourseCards();
}

function clearActivePlanUi() {
  planId = null;
  planData = null;
  setPlanNavEnabled(false);
  dayList.innerHTML = "";
  dayEmpty.classList.remove("hidden");
  btnMid.classList.add("hidden");
  btnFinal.classList.add("hidden");
  dayView.innerHTML = `<p class="empty-hint">選擇左側某一天開始閱讀。</p>`;
  gapsList.innerHTML = "";
  gapsEmpty.classList.remove("hidden");
  gapsSummary.textContent = "尚未載入";
  gapSelectionMode = false;
  selectedGapIds.clear();
  refreshGapActionButtons([]);
  jobLabel.textContent = "尚未載入交接項目";
  const url = new URL(window.location.href);
  url.searchParams.delete("job");
  history.replaceState(null, "", url);
  showView("home");
  renderRecent();
}

const GAP_KIND_LABEL = {
  coverage: "覆蓋",
  structure: "結構",
  contradiction: "矛盾",
  manual: "手動新增",
};

const GAP_SEV_LABEL = {
  high: "高",
  medium: "中",
  low: "低",
};

const GAP_STATUS_LABEL = {
  unresolved: "未解決",
  confirmed: "確認中",
  resolved: "已解決",
};

const GAP_STATUS_ORDER = ["unresolved", "confirmed", "resolved"];

const GAP_COLUMN_NOTE = {
  unresolved: "等待確認或需要釐清的問題",
  confirmed: "正在追蹤、討論或驗證的事項",
  resolved: "已完成交接或確認無誤的事項",
};

function gapStatusCounts(gaps) {
  const counts = { unresolved: 0, confirmed: 0, resolved: 0 };
  gaps.forEach((gap) => {
    const status = gap.status || "unresolved";
    if (status in counts) counts[status] += 1;
  });
  return counts;
}

function refreshGapActionButtons(gaps) {
  const selected = gaps.filter((gap) => selectedGapIds.has(gap.id));
  const counts = gapStatusCounts(selected);
  btnToggleGapSelection.textContent = gapSelectionMode ? "取消選取" : "選取";
  btnToggleGapSelection.classList.toggle("is-active", gapSelectionMode);
  if (!gapSelectionMode) {
    btnExportGaps.textContent = "匯出全部 PDF";
    btnExportGaps.classList.remove("is-selected-export");
    return;
  }
  btnExportGaps.textContent = `已選取 ${selected.length} 項（含未解決 ${counts.unresolved}・確認中 ${counts.confirmed}・已解決 ${counts.resolved}）・匯出 PDF`;
  btnExportGaps.classList.add("is-selected-export");
}

function toggleGapSelection(gapId, checked, gaps) {
  if (checked) selectedGapIds.add(gapId);
  else selectedGapIds.delete(gapId);
  renderGaps({ gaps, summary: { total: gaps.length } });
}

function renderGaps(report) {
  const gaps = (report && report.gaps) || [];
  const summary = (report && report.summary) || {};
  const total = summary.total != null ? summary.total : gaps.length;
  const statusCounts = gapStatusCounts(gaps);
  const validIds = new Set(gaps.map((gap) => gap.id));
  selectedGapIds = new Set([...selectedGapIds].filter((id) => validIds.has(id)));
  gapsSummary.textContent = total
    ? `共 ${total} 項（未解決 ${statusCounts.unresolved} · 確認中 ${statusCounts.confirmed} · 已解決 ${statusCounts.resolved}）`
    : "未發現缺漏";
  gapsList.innerHTML = "";
  refreshGapActionButtons(gaps);
  if (!gaps.length) {
    gapsEmpty.classList.remove("hidden");
    gapsEmpty.textContent = "目前沒有偵測到交接缺口。";
  } else {
    gapsEmpty.classList.add("hidden");
  }

  const byStatus = Object.fromEntries(GAP_STATUS_ORDER.map((status) => [status, []]));
  gaps.forEach((gap) => {
    const status = GAP_STATUS_ORDER.includes(gap.status) ? gap.status : "unresolved";
    byStatus[status].push(gap);
  });
  for (const columnStatus of GAP_STATUS_ORDER) {
    const column = document.createElement("section");
    const columnGaps = byStatus[columnStatus];
    column.className = `gap-column gap-column-${columnStatus}`;
    const selectedInColumn = columnGaps.filter((gap) => selectedGapIds.has(gap.id)).length;
    const allSelected = columnGaps.length > 0 && selectedInColumn === columnGaps.length;
    column.innerHTML = `
      <div class="gap-column-head">
        <h3><span class="gap-status-dot" aria-hidden="true"></span>${GAP_STATUS_LABEL[columnStatus]} <span class="gap-count-badge">${columnGaps.length}</span></h3>
        ${gapSelectionMode ? `<label class="gap-select-all"><input type="checkbox" ${allSelected ? "checked" : ""} ${columnGaps.length ? "" : "disabled"} />全選本欄</label>` : ""}
      </div>
      <p class="gap-column-note">${GAP_COLUMN_NOTE[columnStatus]}</p>
      <ul class="gap-list" aria-label="${GAP_STATUS_LABEL[columnStatus]}交接缺口"></ul>
      <div class="gap-column-add">
        <button type="button" class="gap-quick-add" ${gapSelectionMode ? "disabled" : ""}>＋ 新增疑問</button>
        <form class="gap-column-add-form hidden">
          <input name="title" maxlength="160" placeholder="缺口標題" required />
          <input name="question" maxlength="200" placeholder="尚有疑問的交接缺口" required />
          <div class="gap-column-add-actions"><button type="button" class="ghost gap-add-cancel">取消</button><button type="submit">新增疑問</button></div>
        </form>
      </div>
    `;
    const list = column.querySelector(".gap-list");
    const quickAdd = column.querySelector(".gap-quick-add");
    const addForm = column.querySelector(".gap-column-add-form");
    if (quickAdd && addForm) {
      quickAdd.addEventListener("click", () => {
        quickAdd.classList.add("hidden");
        addForm.classList.remove("hidden");
        addForm.elements.title.focus();
      });
      addForm.querySelector(".gap-add-cancel").addEventListener("click", () => {
        addForm.reset();
        addForm.classList.add("hidden");
        quickAdd.classList.remove("hidden");
      });
      addForm.addEventListener("submit", (event) => {
        event.preventDefault();
        createManualGap(addForm.elements.title.value, addForm.elements.question.value, columnStatus, addForm);
      });
    }
    const selectAll = column.querySelector(".gap-select-all input");
    if (selectAll) {
      selectAll.addEventListener("change", (event) => {
        columnGaps.forEach((gap) => {
          if (event.target.checked) selectedGapIds.add(gap.id);
          else selectedGapIds.delete(gap.id);
        });
        renderGaps({ gaps, summary: { total: gaps.length } });
      });
    }
    if (!gapSelectionMode) {
      column.addEventListener("dragover", (event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        column.classList.add("is-drag-over");
      });
      column.addEventListener("dragleave", (event) => {
        if (!column.contains(event.relatedTarget)) column.classList.remove("is-drag-over");
      });
      column.addEventListener("drop", (event) => {
        event.preventDefault();
        column.classList.remove("is-drag-over");
        const gapId = event.dataTransfer.getData("text/plain") || draggedGapId;
        const gap = gaps.find((item) => item.id === gapId);
        if (gap && (gap.status || "unresolved") !== columnStatus) {
          updateGapStatus(gap.id, columnStatus);
        }
      });
    }
    for (const g of columnGaps) {
    const li = document.createElement("li");
    const status = g.status || "unresolved";
    const isSelected = selectedGapIds.has(g.id);
    li.className = "gap-item" + (status === "resolved" ? " is-resolved" : "") + (isSelected ? " is-selected" : "");
    li.draggable = !gapSelectionMode;
    const kind = GAP_KIND_LABEL[g.kind] || g.kind || "缺漏";
    const sev = GAP_SEV_LABEL[g.severity] || g.severity || "";
    const sources = (g.sources || []).map((p) => `<code>${escapeHtml(p)}</code>`).join(" ");
    li.innerHTML = `
      <div class="gap-head">
        ${gapSelectionMode ? `<label class="gap-card-check"><input type="checkbox" aria-label="選取：${escapeHtml(g.title || "未命名缺漏")}" ${isSelected ? "checked" : ""} /></label>` : ""}
        <span class="gap-kind">${escapeHtml(kind)}</span>
        ${sev ? `<span class="gap-sev sev-${escapeHtml(g.severity || "medium")}">${escapeHtml(sev)}</span>` : ""}
        ${gapSelectionMode ? "" : '<span class="gap-drag-handle" title="拖曳至其他狀態" aria-hidden="true">⠿</span>'}
      </div>
      <h3 class="gap-title">${status === "resolved" ? "✓ " : ""}${escapeHtml(g.title || "未命名缺漏")}</h3>
      <p class="gap-detail">${escapeHtml(g.detail || "")}</p>
      ${sources ? `<p class="gap-sources">依據：${sources}</p>` : ""}
      <p class="gap-q"><span class="gap-q-label">可能疑問</span>${escapeHtml(g.question || "")}</p>
    `;
    const check = li.querySelector(".gap-card-check input");
    if (check) check.addEventListener("change", (event) => toggleGapSelection(g.id, event.target.checked, gaps));
    if (!gapSelectionMode) {
      li.addEventListener("dragstart", (event) => {
        draggedGapId = g.id;
        event.dataTransfer.setData("text/plain", g.id);
        event.dataTransfer.effectAllowed = "move";
        requestAnimationFrame(() => li.classList.add("is-dragging"));
      });
      li.addEventListener("dragend", () => {
        draggedGapId = null;
        li.classList.remove("is-dragging");
        document.querySelectorAll(".gap-column.is-drag-over").forEach((item) => item.classList.remove("is-drag-over"));
      });
    }
    list.appendChild(li);
    }
    if (!columnGaps.length) {
      const empty = document.createElement("li");
      empty.className = "gap-column-empty";
      empty.textContent = "此欄目前沒有交接缺口。";
      list.appendChild(empty);
    }
    gapsList.appendChild(column);
  }
}

async function updateGapStatus(gapId, status) {
  try {
    const res = await fetch(`/api/plans/${planId}/gaps/${encodeURIComponent(gapId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(fmtDetail(data.detail) || "更新失敗");
    }
    renderGaps(data);
  } catch (err) {
    alert("更新交接缺口狀態失敗：" + err.message);
  }
}

btnToggleGapSelection.addEventListener("click", () => {
  if (!planId) {
    alert("請先從交接首頁開啟一個交接項目。");
    return;
  }
  gapSelectionMode = !gapSelectionMode;
  if (!gapSelectionMode) selectedGapIds.clear();
  loadGaps(planId);
});

async function createManualGap(rawTitle, rawQuestion, status, form) {
  if (!planId) {
    alert("請先從交接首頁開啟一個交接項目。");
    return;
  }
  const title = rawTitle.trim();
  const question = rawQuestion.trim();
  if (!title || !question) return;
  try {
    const res = await fetch(`/api/plans/${planId}/gaps`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, question, status }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(fmtDetail(data.detail) || "新增失敗");
    renderGaps(data);
    if (form) form.reset();
  } catch (err) {
    alert(String(err.message || err));
  }
}

btnExportGaps.addEventListener("click", () => {
  if (!planId) {
    alert("請先從交接首頁開啟一個交接項目。");
    return;
  }
  if (gapSelectionMode && !selectedGapIds.size) {
    alert("請先選取至少一項交接缺口。");
    return;
  }
  const params = new URLSearchParams({ status: "all" });
  if (gapSelectionMode) params.set("ids", [...selectedGapIds].join(","));
  window.location.assign(`/api/plans/${planId}/gaps/export/pdf?${params}`);
});

async function loadGaps(id) {
  gapsSummary.textContent = "載入中…";
  try {
    const res = await fetch(`/api/plans/${id}/gaps`);
    const data = await res.json();
    if (!res.ok) throw new Error(fmtDetail(data.detail) || "無法載入交接缺口");
    renderGaps(data);
  } catch (err) {
    gapsList.innerHTML = "";
    gapsEmpty.classList.remove("hidden");
    gapsEmpty.textContent = String(err.message || err);
    gapsSummary.textContent = "載入失敗";
  }
}

function removeRecent(id) {
  saveRecent(loadRecent().filter((x) => x.job_id !== id));
  renderRecent();
  renderCourseCards();
  if (planId === id) clearActivePlanUi();
}

function rememberPlan(id) {
  try { localStorage.setItem(LEGACY_KEY, id); } catch (_) {}
  const url = new URL(window.location.href);
  url.searchParams.set("job", id);
  history.replaceState(null, "", url);
}

function paintGreeting() {
  const now = new Date();
  const hour = now.getHours();
  let greet = "你好";
  if (hour < 12) greet = "早安";
  else if (hour < 18) greet = "午安";
  else greet = "晚安";
  greetKicker.textContent = greet;
  dateChip.innerHTML = `${now.getMonth() + 1}/${now.getDate()}<br/>日`;
}

function renderRecent() {
  const list = loadRecent();
  recentList.innerHTML = "";
  const item = list[0] || null;
  recentEmpty.classList.toggle("hidden", !!item);
  btnClearAll.classList.toggle("hidden", !item);
  if (!item) return;

  const pct = (planData && planId === item.job_id && planData.progress)
    ? (planData.progress.percent_complete || 0)
    : (item.percent_complete || 0);

  const card = document.createElement("div");
  card.className = "recent-card" + (item.job_id === planId ? " active" : "");
  card.innerHTML =
    `<p class="title">${escapeHtml(item.name || "交接計畫")}</p>` +
    `<p class="meta">${escapeHtml(formatDateLabel(item.done_at))}` +
    `${item.days != null ? " · " + item.days + " 天" : ""}</p>` +
    `<div class="bar"><span style="width:${pct}%"></span></div>` +
    `<div class="pct-label"><span>交接進度</span><span>${Math.round(pct)}%</span></div>`;
  card.onclick = () => resumePlan(item.job_id);
  recentList.appendChild(card);
}

function renderCourseCards() {
  const list = loadRecent();
  courseCards.innerHTML = "";
  courseEmpty.classList.toggle("hidden", list.length > 0);
  if (!list.length) return;
  const pct = planData && planData.progress
    ? (planData.progress.percent_complete || 0)
    : 0;
  list.forEach((item) => {
    const card = document.createElement("article");
    card.className = "course-card" + (item.job_id === planId ? " active" : "");
    const isActive = item.job_id === planId;
    const barPct = isActive ? pct : 0;
    card.innerHTML =
      `<h3>${escapeHtml(item.name || "交接計畫")}</h3>` +
      `<p class="meta">${escapeHtml(formatDateLabel(item.done_at))} · ${item.days != null ? item.days + " 天" : "—"}</p>` +
      `<div class="bar"><span style="width:${barPct}%"></span></div>` +
      `<div class="card-actions"></div>`;
    card.onclick = (e) => {
      if (e.target.closest("button")) return;
      resumePlan(item.job_id);
    };
    const actions = card.querySelector(".card-actions");
    const btnOpen = document.createElement("button");
    btnOpen.type = "button";
    btnOpen.className = "ghost";
    btnOpen.textContent = isActive ? "繼續" : "開啟";
    btnOpen.onclick = (e) => {
      e.stopPropagation();
      resumePlan(item.job_id);
    };
    const btnClear = document.createElement("button");
    btnClear.type = "button";
    btnClear.textContent = "清除";
    btnClear.onclick = (e) => {
      e.stopPropagation();
      removeRecent(item.job_id);
    };
    actions.appendChild(btnOpen);
    actions.appendChild(btnClear);
    courseCards.appendChild(card);
  });
}

function allDayQuizzesPassed(progress) {
  const days = (planData && planData.plan && planData.plan.days) || 0;
  if (days < 1) return false;
  const st = progress.day_status || {};
  for (let i = 1; i <= days; i += 1) {
    if (st[String(i)] !== "passed") return false;
  }
  return true;
}

function milestoneQuizStatus(progress, scope) {
  const attempts = (progress.quiz_attempts || []).filter((attempt) => attempt.quiz_key === scope);
  if (attempts.some((attempt) => attempt.passed)) return "passed";
  return attempts.length ? "failed" : "unread";
}

function setMilestone(btn, unlocked, status = "unread") {
  btn.disabled = !unlocked;
  btn.classList.toggle("hidden", !planData);
  btn.classList.toggle("is-locked", !unlocked);
  btn.classList.toggle("is-passed", status === "passed");
  btn.classList.toggle("is-failed", status === "failed");
  const baseLabel = btn === btnMid ? "交接期中查核" : "上手驗收";
  btn.textContent = status === "passed" ? `${baseLabel} · 已通過` : status === "failed" ? `${baseLabel} · 未通過` : baseLabel;
  if (btn === btnFinal) {
    btn.title = unlocked
      ? "已通過全部每日查核，可進行上手驗收"
      : "需先通過全部每日查核後才能解鎖上手驗收";
  }
}

function renderCourseList(progress) {
  const items = (planData && planData.plan && planData.plan.items) || [];
  dayList.innerHTML = "";
  dayEmpty.classList.toggle("hidden", items.length > 0);
  items.forEach((it) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    const st = (progress.day_status || {})[String(it.day)] || "unread";
    const label = ST_LABEL[st] || st;
    b.classList.toggle("is-passed", st === "passed");
    b.innerHTML =
      `<span>Day ${it.day}</span>` +
      `<span class="st ${escapeHtml(st)}">${escapeHtml(label)}</span>` +
      `<span class="theme">${escapeHtml(it.theme || "")}</span>` +
      `<span class="go">${st === "passed" ? "已完成" : it.day === currentDay ? "進行中 →" : "開始 →"}</span>`;
    if (it.day === currentDay) b.classList.add("active");
    b.onclick = () => openDay(it.day);
    li.appendChild(b);
    dayList.appendChild(li);
  });
}

function renderProgress(progress) {
  const pct = progress.percent_complete != null ? progress.percent_complete : 0;
  setMilestone(btnMid, !!progress.midterm_unlocked, milestoneQuizStatus(progress, "midterm"));
  // 前端再以每日通過狀態鎖定，避免舊 progress 殘留 final_unlocked
  setMilestone(btnFinal, allDayQuizzesPassed(progress), milestoneQuizStatus(progress, "final"));
  renderCourseList(progress);
  renderCourseCards();
  if (planId) {
    const list = loadRecent();
    const idx = list.findIndex((x) => x.job_id === planId);
    if (idx >= 0) {
      list[idx] = { ...list[idx], percent_complete: pct };
      saveRecent(list);
    }
  }
  renderRecent();
}

async function openDay(day) {
  currentDay = day;
  showView("learn");
  const res = await fetch(`/api/plans/${planId}/days/${day}`);
  const data = await res.json();
  if (!res.ok) throw new Error(fmtDetail(data.detail) || "讀取失敗");
  if (planData) planData.progress = data.progress;
  renderProgress(data.progress);
  const d = data.day;
  let html =
    `<h2 class="day-heading">Day ${d.day} — ${escapeHtml(d.theme || "")}</h2>` +
    `<div class="day-tools">` +
    `<a href="/api/plans/${planId}/days/${day}/notes.pdf" target="_blank" rel="noreferrer">下載今日重點筆記 PDF</a>` +
    `</div>`;
  (d.blocks || []).forEach((blk) => {
    html += `<div class="block"><h3>${escapeHtml(blk.title || blk.type)}</h3><div class="body">${escapeHtml(blk.body || "")}</div>`;
    if (blk.paths && blk.paths.length) {
      html += `<div class="paths">` + blk.paths.map((p) =>
        `<a href="/api/plans/${planId}/days/${day}/files/${encodeURIComponent(p)}" target="_blank" rel="noreferrer">${escapeHtml(p)}</a>`
      ).join("") + `</div>`;
    }
    html += `</div>`;
  });
  html += `<button type="button" class="enter-quiz" id="btnEnterQuiz">進入本日測驗</button>`;
  dayView.innerHTML = html;
  document.getElementById("btnEnterQuiz").onclick = () => loadQuiz("day", day);
}

async function loadQuiz(scope, day) {
  const url = scope === "day"
    ? `/api/plans/${planId}/quizzes/day/${day}`
    : `/api/plans/${planId}/quizzes/${scope}`;
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) {
    dayView.innerHTML = `<p class="err">${escapeHtml(fmtDetail(data.detail) || "無法載入測驗")}</p>`;
    return;
  }
  const items = data.items || [];
  const reviewMode = data.review_mode === true;
  const title = scope === "day" ? `Day ${day} 每日查核` : scope === "midterm" ? "交接期中查核" : "上手驗收";
  let html = "";
  if (scope === "day") {
    html += `<button type="button" class="back-lesson" id="btnBackLesson">← 返回教材</button>`;
  }
  html += `<h3 class="quiz-heading">${title}</h3>`;
  if (!items.length) {
    dayView.innerHTML = html + `<p class="err">此範圍沒有題目</p>`;
    const back = document.getElementById("btnBackLesson");
    if (back) back.onclick = () => openDay(day);
    return;
  }
  if (reviewMode) html += `<p class="quiz-review-note">本日測驗已通過，以下為題目與正確答案。</p>`;
  if (!reviewMode) html += `<form id="quizForm">`;
  items.forEach((q, idx) => {
    html += `<div class="quiz-item"><div><strong>${idx + 1}. ${escapeHtml(q.stem)}</strong></div>`;
    if (reviewMode) {
      html += `<p class="quiz-answer"><span>正確答案</span>${escapeHtml(q.answer || "")}</p>`;
      if (q.explanation) html += `<p class="quiz-explanation">${escapeHtml(q.explanation)}</p>`;
    } else if (q.choices && q.choices.length) {
      q.choices.forEach((ch, ci) => {
        const letter = String.fromCharCode(65 + ci);
        html += `<label><input type="radio" name="${escapeHtml(q.id)}" value="${ci}" data-text="${escapeHtml(ch)}" /> ${letter}. ${escapeHtml(ch)}</label>`;
      });
    } else {
      html += `<input name="${escapeHtml(q.id)}" class="quiz-text-input" />`;
    }
    html += `</div>`;
  });
  if (!reviewMode) html += `<button type="submit">交卷</button></form><div id="quizResult" class="msg"></div>`;
  dayView.innerHTML = html;
  const back = document.getElementById("btnBackLesson");
  if (back) back.onclick = () => openDay(day);
  if (reviewMode) return;
  document.getElementById("quizForm").onsubmit = async (e) => {
    e.preventDefault();
    const answers = {};
    items.forEach((q) => {
      const checked = e.target.querySelector(`input[name="${CSS.escape(q.id)}"]:checked`);
      const textInput = e.target.querySelector(`input[name="${CSS.escape(q.id)}"]:not([type="radio"])`);
      if (checked) answers[q.id] = checked.getAttribute("data-text") || checked.value;
      else if (textInput) answers[q.id] = textInput.value;
    });
    const body = { scope, day: scope === "day" ? day : null, answers };
    const r = await fetch(`/api/plans/${planId}/quizzes/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const out = await r.json();
    const el = document.getElementById("quizResult");
    if (!r.ok) {
      el.textContent = fmtDetail(out.detail) || "交卷失敗";
      return;
    }
    const resu = out.result;
    el.textContent = `得分 ${(resu.score * 100).toFixed(0)}%（${resu.correct}/${resu.total}）${resu.passed ? " · 通過" : " · 未通過"}`;
    if (planData) planData.progress = out.progress;
    renderProgress(out.progress);
  };
}

function openMilestone(scope, title, hint) {
  if (scope === "midterm" && btnMid.disabled) return;
  if (scope === "final") {
    const progress = (planData && planData.progress) || {};
    if (!allDayQuizzesPassed(progress) || btnFinal.disabled) {
      dayView.innerHTML =
        `<h2 class="milestone-heading">上手驗收</h2>` +
        `<p class="err">需先通過全部每日查核後才能解鎖上手驗收。</p>`;
      showView("learn");
      return;
    }
  }
  showView("learn");
  dayView.innerHTML = `<h2 class="milestone-heading">${title}</h2><p class="meta">${hint}</p>`;
  loadQuiz(scope);
}

function appendAssistantBubble(role, text, meta) {
  const div = document.createElement("div");
  div.className = `assistant-bubble ${role}`;
  div.textContent = text;
  if (meta) {
    const m = document.createElement("span");
    m.className = "assistant-meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  assistantLog.appendChild(div);
  assistantLog.scrollTop = assistantLog.scrollHeight;
  return div;
}

function showTypingIndicator() {
  const el = document.createElement("div");
  el.className = "assistant-typing";
  el.id = "assistantTyping";
  el.setAttribute("aria-label", "小助手輸入中");
  el.innerHTML = "<span></span><span></span><span></span>";
  assistantLog.appendChild(el);
  assistantLog.scrollTop = assistantLog.scrollHeight;
  return el;
}

function hideTypingIndicator() {
  const el = document.getElementById("assistantTyping");
  if (el) el.remove();
}

assistantForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  assistantError.textContent = "";
  if (!planId) {
    assistantError.textContent = "請先載入交接計畫";
    openChatPanel();
    return;
  }
  const question = (assistantQ.value || "").trim();
  if (!question) {
    assistantError.textContent = "請輸入問題";
    return;
  }
  if (question.length > 200) {
    assistantError.textContent = "問題請控制在 200 字以內";
    return;
  }
  openChatPanel();
  appendAssistantBubble("user", question);
  assistantQ.value = "";
  assistantSend.disabled = true;
  showTypingIndicator();
  try {
    const r = await fetch(`/api/plans/${planId}/assistant`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, day: currentDay }),
    });
    const out = await r.json().catch(() => ({}));
    hideTypingIndicator();
    if (!r.ok) throw new Error(fmtDetail(out.detail) || "小助手回答失敗");
    const cites = (out.citations || [])
      .map((c) => c.path)
      .filter(Boolean)
      .slice(0, 3)
      .join(" · ");
    appendAssistantBubble("bot", out.answer || "（無內容）", cites || null);
  } catch (err) {
    hideTypingIndicator();
    assistantError.textContent = String(err.message || err);
  } finally {
    assistantSend.disabled = false;
    assistantQ.focus();
  }
});

btnFabChat.addEventListener("click", () => toggleChatPanel());
btnCloseChat.addEventListener("click", () => closeChatPanel());

async function openLearn(id, meta) {
  planId = id;
  assistantLog.innerHTML = "";
  assistantError.textContent = "";
  const res = await fetch(`/api/plans/${id}`);
  const data = await res.json();
  if (!res.ok) throw new Error(fmtDetail(data.detail) || "無法載入計畫");
  planData = data;

  const existing = findRecent(id);
  const days = (data.plan && data.plan.days) || (meta && meta.days) || (existing && existing.days) || null;
  const name = (meta && meta.name) || (existing && existing.name) || "交接計畫";
  upsertRecent({
    job_id: id,
    name,
    days,
    done_at: (existing && existing.done_at) || (meta && meta.done_at) || new Date().toISOString(),
    percent_complete: (data.progress && data.progress.percent_complete) || 0,
  });

  rememberPlan(id);
  setBadge("done");
  jobLabel.textContent = displayTitle(findRecent(id) || { name, days, done_at: new Date().toISOString() });
  messageEl.textContent = "交接計畫已載入";
  jobBar.style.width = "100%";
  errorEl.textContent = "";
  recentError.textContent = "";
  setPlanNavEnabled(true);
  renderProgress(data.progress);
  const items = data.plan.items || [];
  let startDay = 1;
  for (const it of items) {
    const st = (data.progress.day_status || {})[String(it.day)];
    if (st !== "passed") { startDay = it.day; break; }
  }
  await openDay(startDay);
}

async function resumePlan(id) {
  recentError.textContent = "";
  const trimmed = (id || "").trim();
  if (!trimmed) return;
  try {
    const jobRes = await fetch(`/api/jobs/${trimmed}`);
    const job = await jobRes.json();
    if (!jobRes.ok) throw new Error(fmtDetail(job.detail) || "找不到紀錄");
    if (job.status !== "done") throw new Error(`狀態為 ${job.status}，尚未完成`);
    if (!(job.outputs && job.outputs.plan_ready)) {
      throw new Error("此紀錄沒有交接計畫（請重新上傳）");
    }
    await openLearn(trimmed);
  } catch (err) {
    recentError.textContent = String(err.message || err);
  }
}

async function poll(jobId) {
  const res = await fetch(`/api/jobs/${jobId}`);
  if (!res.ok) throw new Error(`查詢失敗 HTTP ${res.status}`);
  const data = await res.json();
  setBadge(data.status);
  const pct = (data.progress && data.progress.percent != null) ? data.progress.percent : 0;
  jobBar.style.width = `${pct}%`;
  messageEl.textContent = (data.progress && data.progress.message) || data.status;
  errorEl.textContent = data.error || "";

  if (data.status === "done") {
    clearInterval(timer);
    timer = null;
    submitBtn.disabled = false;
    if (data.outputs && data.outputs.plan_ready) {
      const meta = pendingMeta && pendingMeta.job_id === jobId
        ? { ...pendingMeta, done_at: new Date().toISOString() }
        : { name: "交接計畫", done_at: new Date().toISOString() };
      pendingMeta = null;
      await openLearn(jobId, meta);
    } else {
      errorEl.textContent = "Job 完成但缺少交接計畫";
    }
    return;
  }
  if (data.status === "failed") {
    clearInterval(timer);
    timer = null;
    submitBtn.disabled = false;
    pendingMeta = null;
  }
}

[navHome, navLearn, navGaps].forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.disabled) return;
    showView(btn.dataset.view);
  });
});

btnNewUpload.addEventListener("click", () => {
  if (uploadPanel.classList.contains("hidden")) openUploadPanel();
  else closeUploadPanel();
});

btnToggleSidebar.addEventListener("click", () => {
  applySidebarCollapsed(!shell.classList.contains("sidebar-collapsed"));
});

btnMid.onclick = () => openMilestone("midterm", "交接期中查核", "進度已達半，可開始作答。");
btnFinal.onclick = () =>
  openMilestone(
    "final",
    "上手驗收",
    "需先通過全部每日查核後才能作答。"
  );
btnClearAll.onclick = () => {
  saveRecent([]);
  renderRecent();
  renderCourseCards();
  if (planId) clearActivePlanUi();
};

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById("file");
  if (!fileInput.files.length) {
    errorEl.textContent = "請先選擇 ZIP";
    setBadge("failed");
    return;
  }
  if (timer) { clearInterval(timer); timer = null; }
  submitBtn.disabled = true;
  setPlanNavEnabled(false);
  errorEl.textContent = "";
  recentError.textContent = "";
  setBadge("uploading");
  messageEl.textContent = "上傳中…";
  jobBar.style.width = "5%";
  dayList.innerHTML = "";
  dayEmpty.classList.remove("hidden");
  btnMid.classList.add("hidden");
  btnFinal.classList.add("hidden");
  dayView.innerHTML = `<p class="empty-hint">選擇左側某一天開始閱讀。</p>`;

  const file = fileInput.files[0];
  const daysVal = Number(document.getElementById("days").value) || 5;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("days", String(daysVal));
  try {
    const res = await fetch("/api/jobs", { method: "POST", body: fd });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(fmtDetail(body.detail) || `上傳失敗 HTTP ${res.status}`);
    const jobId = body.job_id;
    pendingMeta = { job_id: jobId, name: file.name || "upload.zip", days: daysVal };
    setBadge("queued");
    messageEl.textContent = "已建立任務…";
    await poll(jobId);
    timer = setInterval(() => {
      poll(jobId).catch((err) => { errorEl.textContent = String(err.message || err); });
    }, 2000);
  } catch (err) {
    setBadge("failed");
    errorEl.textContent = String(err.message || err);
    submitBtn.disabled = false;
    pendingMeta = null;
  }
});

(async function boot() {
  paintGreeting();
  renderRecent();
  renderCourseCards();
  setPlanNavEnabled(false);
  showView("home");
  try {
    applySidebarCollapsed(localStorage.getItem(SIDEBAR_KEY) === "1");
  } catch (_) {
    applySidebarCollapsed(false);
  }
  // 預設停在交接首頁；有 ?job= 時僅預載計畫狀態，不自動跳每日任務
  const params = new URLSearchParams(window.location.search);
  const fromQuery = params.get("job");
  const recent = loadRecent();
  let fromLegacy = null;
  try { fromLegacy = localStorage.getItem(LEGACY_KEY); } catch (_) {}
  const id = fromQuery || (recent[0] && recent[0].job_id) || fromLegacy;
  if (!id) return;
  try {
    const jobRes = await fetch(`/api/jobs/${id}`);
    const job = await jobRes.json();
    if (!jobRes.ok || job.status !== "done" || !(job.outputs && job.outputs.plan_ready)) return;
    const res = await fetch(`/api/plans/${id}`);
    const data = await res.json();
    if (!res.ok) return;
    planId = id;
    planData = data;
    const existing = findRecent(id);
    upsertRecent({
      job_id: id,
      name: (existing && existing.name) || "交接計畫",
      days: (data.plan && data.plan.days) || (existing && existing.days) || null,
      done_at: (existing && existing.done_at) || new Date().toISOString(),
      percent_complete: (data.progress && data.progress.percent_complete) || 0,
    });
    rememberPlan(id);
    jobLabel.textContent = displayTitle(findRecent(id) || { name: "交接計畫" });
    setPlanNavEnabled(true);
    renderProgress(data.progress);
    showView("home");
  } catch (_) {}
})();
