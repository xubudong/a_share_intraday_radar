const state = {
  dashboard: null,
  stocks: [],
  group: "全部",
  expanded: null,
  timer: null,
  refreshPollTimer: null,
  sort: { key: "signal", direction: "desc" },
  viewingSnapshot: null,  // snapshot ID or null for live
  noteScope: "全部",
  sectorNotes: [],
  stockNotes: {},
  radarCollapsed: true,
};

const actionableSignals = new Set(["可试仓", "二次确认", "突破观察"]);
const groupFamilies = [
  {
    label: "电子元件",
    groups: ["MLCC（被动元件）", "PCB", "覆铜板", "玻璃基板", "玻璃玻纤 / 电子布"],
  },
  { label: "化工", prefixes: ["化工-"], groups: ["工业气体"] },
  { label: "有色", prefixes: ["有色-"] },
  { label: "新能源", prefixes: ["新能源-"], groups: ["铜箔"] },
  { label: "芯片", prefixes: ["半导体芯片-"], groups: ["存储芯片", "先进封装"] },
  { label: "光通信", prefixes: ["光模块-"], groups: ["光纤"] },
  { label: "半导体材料", prefixes: ["半导体材料-"] },
  { label: "电网设备", prefixes: ["电网设备-"] },
  { label: "机器人", groups: ["机器人核心"] },
  { label: "算力基础设施", groups: ["液冷核心"] },
  { label: "医药", prefixes: ["医药-"] },
];

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  bootstrap();
  state.timer = window.setInterval(() => requestRefresh(false), 60000);
});

function bindEvents() {
  document.getElementById("refreshBtn").addEventListener("click", () => requestRefresh(false));
  document.getElementById("historyBtn").addEventListener("click", () => requestRefresh(true));
  document.getElementById("snapshotBtn").addEventListener("click", openSnapshotPanel);
  document.getElementById("snapshotClose").addEventListener("click", closeSnapshotPanel);
  document.getElementById("snapshotOverlay").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeSnapshotPanel();
  });
  document.getElementById("radarToggle").addEventListener("click", toggleRadarPanel);
  document.getElementById("noteSaveBtn").addEventListener("click", saveSectorNote);
  document.getElementById("noteTodayBtn").addEventListener("click", () => {
    document.getElementById("noteDate").value = localToday();
    populateNoteEditor();
  });
  document.getElementById("noteDate").addEventListener("change", populateNoteEditor);
  ["starOnly", "holdingOnly", "actionableOnly", "overheatOnly"].forEach((id) => {
    document.getElementById(id).addEventListener("change", renderTable);
  });
  document.getElementById("searchInput").addEventListener("input", renderTable);
  document.addEventListener("click", (event) => {
    const copyBtn = event.target.closest(".copy-code");
    if (copyBtn) {
      event.stopPropagation();
      copyCode(copyBtn.dataset.code, copyBtn);
      return;
    }
    const starBtn = event.target.closest(".star-toggle");
    if (starBtn) {
      event.stopPropagation();
      toggleStar(starBtn.dataset.code, starBtn);
      return;
    }
    const holdingBtn = event.target.closest(".holding-toggle");
    if (holdingBtn) {
      event.stopPropagation();
      toggleHolding(holdingBtn.dataset.code, holdingBtn);
      return;
    }
    const groupStarBtn = event.target.closest(".group-star-toggle");
    if (groupStarBtn) {
      event.preventDefault();
      event.stopPropagation();
      toggleGroupStar(groupStarBtn.dataset.group, groupStarBtn);
      return;
    }
  });
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sort.key === key) {
        state.sort.direction = state.sort.direction === "desc" ? "asc" : "desc";
      } else {
        state.sort = { key, direction: defaultSortDirection(key) };
      }
      renderTable();
    });
  });
}

async function bootstrap() {
  try {
    await loadData();
  } catch (err) {
    showRefreshError(err);
  }
  document.getElementById("noteDate").value = localToday();
  await loadSectorNotes(state.noteScope);
  await requestRefresh(false);
}

async function loadData() {
  const [dashboard, stocks] = await Promise.all([
    fetchJson("/api/dashboard"),
    fetchJson("/api/stocks"),
  ]);
  state.dashboard = dashboard;
  state.stocks = stocks.stocks || [];
  render();
  return dashboard;
}

async function requestRefresh(forceHistory) {
  if (!forceHistory && state.dashboard?.refresh?.refreshing) {
    setBusy(true);
    scheduleRefreshPoll();
    return;
  }

  setBusy(true);
  try {
    const response = await fetch(
      `/api/refresh?force_history=${forceHistory ? "true" : "false"}`,
      { method: "POST" },
    );
    if (!response.ok) throw new Error(`${response.status}`);
    const status = await response.json();
    const dashboard = await loadData();
    if (status.refreshing || dashboard.refresh?.refreshing) {
      scheduleRefreshPoll();
    } else {
      setBusy(false);
    }
  } catch (err) {
    showRefreshError(err);
    setBusy(false);
  }
}

function scheduleRefreshPoll() {
  window.clearTimeout(state.refreshPollTimer);
  state.refreshPollTimer = window.setTimeout(pollRefresh, 1500);
}

async function pollRefresh() {
  try {
    const dashboard = await fetchJson("/api/dashboard");
    state.dashboard = dashboard;
    renderHeader();
    if (dashboard.refresh?.refreshing) {
      scheduleRefreshPoll();
      return;
    }
    await loadData();
  } catch (err) {
    showRefreshError(err);
  }
  setBusy(false);
}

function showRefreshError(err) {
  document.getElementById("dataStatus").textContent = `数据源：刷新失败 ${err.message}`;
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

function setBusy(busy) {
  document.getElementById("refreshBtn").disabled = busy;
  document.getElementById("historyBtn").disabled = busy;
  document.getElementById("refreshBtn").textContent = busy ? "…" : "↻";
}

function render() {
  renderHeader();
  renderSummary();
  renderRadar();
  renderGroups();
  renderTable();
}

function renderHeader() {
  const dashboard = state.dashboard || {};
  const session = dashboard.market_session || {};
  const badge = document.getElementById("sessionBadge");
  badge.textContent = session.label || "状态";
  badge.className = `badge ${session.is_open ? "open" : "closed"}`;
  document.getElementById("lastUpdated").textContent = `刷新：${formatTime(dashboard.updated_at)}`;
  const source = dashboard.data_source || {};
  const refresh = dashboard.refresh || {};
  const errCount = (source.errors || []).length;
  document.getElementById("dataStatus").textContent = refresh.refreshing
    ? `数据源：后台刷新中${refresh.pending_force_history ? "，已排队历史刷新" : ""}`
    : errCount > 0
      ? `数据源：部分异常 ${errCount} 条`
      : "数据源：EastMoney 正常";
}

function renderSummary() {
  const summary = (state.dashboard && state.dashboard.summary) || {};
  const items = [
    ["全池", summary.total ?? "--"],
    ["星标", summary.stars ?? "--"],
    ["买点", summary.actionable ?? "--"],
    ["过热", summary.overheated ?? "--"],
    ["走弱", summary.weak ?? "--"],
  ];
  const up = summary.up ?? 0;
  const down = summary.down ?? 0;
  const flat = summary.flat ?? 0;
  const avgPct = summary.avg_pct ?? 0;
  const avgPctMain = summary.avg_pct_main ?? 0;
  const avgPctGem = summary.avg_pct_gem ?? 0;
  const avgPctT1 = summary.avg_pct_t1;
  const avgPctT2 = summary.avg_pct_t2;
  const avgPctT3 = summary.avg_pct_t3;
  const avgClass = avgPct > 0 ? "pos" : avgPct < 0 ? "neg" : "";
  const avgMainClass = avgPctMain > 0 ? "pos" : avgPctMain < 0 ? "neg" : "";
  const avgGemClass = avgPctGem > 0 ? "pos" : avgPctGem < 0 ? "neg" : "";
  const pctClass = (v) => v > 0 ? "pos" : v < 0 ? "neg" : "";
  const fmtPct = (v) => v === null || v === undefined
    ? "--"
    : (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  const marketAnchorHtml = (index) => {
    const anchors = [
      ["昨收", index.prev_close],
      ["今开", index.open],
    ].filter(([, value]) => value !== null && value !== undefined);
    if (!anchors.length) return "";
    return `<div class="market-index-anchor">${
      anchors.map(([label, value]) => `<span>${label} ${formatPrice(value)}</span>`).join("")
    }</div>`;
  };
  const marketIndices = (state.dashboard && state.dashboard.market_indices) || [];
  const marketIndexHtml = marketIndices.length
    ? marketIndices.map((index) => {
      const pct = index.pct_chg;
      const change = index.change;
      const cls = pctClass(pct);
      return `
        <div class="market-index-item">
          <div>
            <div class="market-index-name">${escapeHtml(index.name || index.code)}</div>
            <div class="market-index-point">${formatPrice(index.price)}</div>
            ${marketAnchorHtml(index)}
            <div class="market-index-change ${cls}">
              ${change === null || change === undefined ? "--" : (change >= 0 ? "+" : "") + Number(change).toFixed(2)}
              <span>${fmtPct(pct)}</span>
            </div>
          </div>
          <div class="market-index-chart">${marketIndexSparklineSVG(index.intraday, pct)}</div>
        </div>
      `;
    }).join("")
    : '<div class="muted market-index-empty">等待大盘数据...</div>';
  document.getElementById("marketIndexPanel").innerHTML = `
    <div class="market-index-list">${marketIndexHtml}</div>
  `;
  document.getElementById("summaryGrid").innerHTML =
    items.map(([label, value]) => `
      <div class="summary-item">
        <div class="summary-label">${label}</div>
        <div class="summary-value">${value}</div>
      </div>
    `).join("")
    + `
      <div class="summary-item summary-wide">
        <div class="summary-label">涨跌对比</div>
        <div class="summary-value up-down-bar">
          <span class="pos">${up}涨</span>
          <span class="bar-track"><span class="bar-fill up-fill" style="width:${up/(up+down+flat||1)*100}%"></span><span class="bar-fill down-fill" style="width:${down/(up+down+flat||1)*100}%"></span></span>
          <span class="neg">${down}跌</span>
          ${flat ? `<span class="muted">${flat}平</span>` : ""}
        </div>
      </div>
      <div class="summary-item">
        <div class="summary-label">平均涨幅</div>
        <div class="summary-value ${avgClass}">${fmtPct(avgPct)}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">主板</div>
        <div class="summary-value ${avgMainClass}">${fmtPct(avgPctMain)}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">创业/科创</div>
        <div class="summary-value ${avgGemClass}">${fmtPct(avgPctGem)}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">T1平均涨跌幅</div>
        <div class="summary-value ${pctClass(avgPctT1)}">${fmtPct(avgPctT1)}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">T2平均涨跌幅</div>
        <div class="summary-value ${pctClass(avgPctT2)}">${fmtPct(avgPctT2)}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">T3平均涨跌幅</div>
        <div class="summary-value ${pctClass(avgPctT3)}">${fmtPct(avgPctT3)}</div>
      </div>
    `;
}

function renderRadar() {
  const radar = (state.dashboard && state.dashboard.radar) || [];
  document.getElementById("radarCount").textContent = `${radar.length} 只`;
  renderRadarPanelState();
  const el = document.getElementById("radarList");
  if (!radar.length) {
    el.innerHTML = `<div class="empty">当前没有进入买点雷达的标的。</div>`;
    return;
  }
  el.innerHTML = radar.map((stock) => `
    <article class="radar-card">
      <div class="radar-title">
        <span>${stock.star ? '<button class="star-toggle starred" data-code="' + stock.code + '" title="取消星标" aria-label="取消星标">★</button> ' : '<button class="star-toggle" data-code="' + stock.code + '" title="加星标" aria-label="加星标">☆</button> '}${holdingButton(stock)} ${stock.name}</span>
        ${signalPill(stock.signal.signal)}
      </div>
      <div class="stock-code">${stock.code}${boardBadge(stock.code)} · ${stock.group}</div>
      <div class="radar-metrics">
        <span>价格 ${formatPrice(stock.price)}</span>
        <span class="${numClass(stock.quote?.pct_chg)}">${formatPct(stock.quote?.pct_chg)}</span>
        <span>RSI ${formatNumber(stock.indicators?.rsi14, 1)}</span>
        <span>量比 ${formatNumber(stock.indicators?.volume_ratio, 2)}</span>
      </div>
      <div class="radar-action">${stock.signal.action}</div>
    </article>
  `).join("");
}

function toggleRadarPanel() {
  state.radarCollapsed = !state.radarCollapsed;
  renderRadarPanelState();
}

function renderRadarPanelState() {
  const panel = document.getElementById("radarPanel");
  const button = document.getElementById("radarToggle");
  panel.classList.toggle("collapsed", state.radarCollapsed);
  button.textContent = state.radarCollapsed ? "展开" : "收起";
  button.setAttribute("aria-expanded", String(!state.radarCollapsed));
}

function renderGroups() {
  const savedGroupStats = (state.dashboard && state.dashboard.group_stats) || {};
  const computedGroupStats = computeGroupStatsFromStocks();
  const groupStats = { ...computedGroupStats, ...savedGroupStats };
  const allGroups = Array.from(new Set(
    state.stocks.flatMap((stock) => stock.groups?.length ? stock.groups : [stock.group])
  ));
  const familyStats = Object.fromEntries(
    groupFamilies.map((family) => [family.label, computeFamilyStats(family)])
  );
  const otherGroups = allGroups
    .filter((group) => !groupFamilies.some((family) => groupMatchesFamily(group, family)))
    .sort();
  const selections = ["全部", ...groupFamilies.map((family) => family.label), ...allGroups];
  if (!selections.includes(state.group)) state.group = "全部";

  const groupButton = (group, display = group) => {
    const gs = groupStats[group] || {};
    const avg = gs.avg_pct;
    const avgTag = avg === undefined || avg === null
      ? '<span class="group-pct muted">--</span>'
      : `<span class="group-pct ${avg > 0 ? 'pos' : avg < 0 ? 'neg' : 'muted'}">${avg >= 0 ? '+' : ''}${avg.toFixed(2)}%</span>`;
    const starred = Boolean(gs.star);
    const starTag = group === "全部"
      ? ""
      : `<span class="group-star-toggle ${starred ? "starred" : ""}" data-group="${escapeHtml(group)}" title="${starred ? "取消板块星标" : "板块加星标"}" aria-label="${starred ? "取消板块星标" : "板块加星标"}">${starred ? "★" : "☆"}</span>`;
    return `<button class="${group === state.group ? "active" : ""}" data-group="${escapeHtml(group)}" title="${escapeHtml(group)}">${escapeHtml(display)}${avgTag}${starTag}</button>`;
  };

  const familyStatsTag = (stats) => {
    if (!stats || !stats.total) return '<span class="family-stats muted">--</span>';
    const avg = stats.avg_pct;
    const avgTag = avg === null || avg === undefined
      ? '<span class="group-pct muted">--</span>'
      : `<span class="group-pct ${avg > 0 ? 'pos' : avg < 0 ? 'neg' : 'muted'}">${avg >= 0 ? '+' : ''}${avg.toFixed(2)}%</span>`;
    const flatText = stats.flat ? `<span class="muted">/${stats.flat}平</span>` : "";
    return `${avgTag}<span class="family-breadth"><span class="pos">${stats.up}涨</span>/<span class="neg">${stats.down}跌</span>${flatText}</span>`;
  };

  let html = groupButton("全部");
  for (const family of groupFamilies) {
    const familyGroups = allGroups
      .filter((group) => groupMatchesFamily(group, family))
      .sort((a, b) => groupDisplayForFamily(a, family).localeCompare(groupDisplayForFamily(b, family), "zh-CN"));
    if (!familyGroups.length) continue;
    const stats = familyStats[family.label];
    const familyTitle = `${family.label}：${stats.total}只，${stats.up}涨/${stats.down}跌${stats.flat ? `/${stats.flat}平` : ""}`;
    html += `<div class="group-cluster"><button class="group-family-btn ${family.label === state.group ? "active" : ""}" data-family="${escapeHtml(family.label)}" title="${escapeHtml(familyTitle)}"><span>${escapeHtml(family.label)}</span>${familyStatsTag(stats)}</button>`;
    html += familyGroups
      .map((group) => groupButton(group, groupDisplayForFamily(group, family)))
      .join("");
    html += "</div>";
  }
  if (otherGroups.length) {
    html += '<div class="group-cluster"><span class="group-cluster-label">其他</span>';
    html += otherGroups.map((group) => groupButton(group)).join("");
    html += "</div>";
  }

  document.getElementById("groupFilter").innerHTML = html;
  document.querySelectorAll("#groupFilter button[data-group]").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectSector(btn.dataset.group);
    });
  });
  document.querySelectorAll("#groupFilter button[data-family]").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectSector(btn.dataset.family);
    });
  });
}

function computeGroupStatsFromStocks() {
  const rawStats = {};
  for (const stock of state.stocks) {
    const groups = stock.groups?.length ? stock.groups : [stock.group];
    const pct = stock.quote?.pct_chg;
    for (const group of groups) {
      if (!group) continue;
      if (!rawStats[group]) rawStats[group] = { total: 0, signals: {}, pcts: [] };
      rawStats[group].total += 1;
      if (pct !== null && pct !== undefined) rawStats[group].pcts.push(pct);
    }
  }
  return Object.fromEntries(
    Object.entries(rawStats).map(([group, stats]) => [
      group,
      {
        total: stats.total,
        signals: stats.signals,
        avg_pct: stats.pcts.length
          ? Number((stats.pcts.reduce((sum, pct) => sum + pct, 0) / stats.pcts.length).toFixed(2))
          : null,
      },
    ])
  );
}

function computeFamilyStats(family) {
  const stats = { total: 0, up: 0, down: 0, flat: 0, pcts: [] };
  for (const stock of state.stocks) {
    const groups = stock.groups?.length ? stock.groups : [stock.group];
    if (!groups.some((group) => groupMatchesFamily(group, family))) continue;
    stats.total += 1;
    const pct = stock.quote?.pct_chg;
    if (pct === null || pct === undefined) {
      stats.flat += 1;
    } else if (pct > 0) {
      stats.up += 1;
      stats.pcts.push(pct);
    } else if (pct < 0) {
      stats.down += 1;
      stats.pcts.push(pct);
    } else {
      stats.flat += 1;
      stats.pcts.push(pct);
    }
  }
  return {
    total: stats.total,
    up: stats.up,
    down: stats.down,
    flat: stats.flat,
    avg_pct: stats.pcts.length
      ? Number((stats.pcts.reduce((sum, pct) => sum + pct, 0) / stats.pcts.length).toFixed(2))
      : null,
  };
}

function groupMatchesFamily(group, family) {
  const prefixes = family.prefixes || (family.prefix ? [family.prefix] : []);
  return prefixes.some((prefix) => group.startsWith(prefix)) || (family.groups || []).includes(group);
}

function groupDisplayForFamily(group, family) {
  const prefixes = family.prefixes || (family.prefix ? [family.prefix] : []);
  const matchedPrefix = prefixes.find((prefix) => group.startsWith(prefix));
  if (matchedPrefix) return group.slice(matchedPrefix.length);
  return group;
}

function selectSector(scope) {
  state.group = scope;
  state.noteScope = scope;
  document.getElementById("noteDate").value = localToday();
  document.getElementById("noteContent").value = "";
  renderGroups();
  renderTable();
  loadSectorNotes(scope);
}

async function loadSectorNotes(scope) {
  const requestedScope = scope;
  const title = document.getElementById("noteScopeTitle");
  const timeline = document.getElementById("noteTimeline");
  title.textContent = scope;
  timeline.innerHTML = '<div class="note-empty">加载笔记...</div>';
  setNoteStatus("");
  try {
    const notes = await fetchJson(`/api/sector-notes?scope=${encodeURIComponent(scope)}`);
    if (state.noteScope !== requestedScope) return;
    state.sectorNotes = notes;
    renderNoteTimeline();
    populateNoteEditor();
  } catch (err) {
    if (state.noteScope !== requestedScope) return;
    state.sectorNotes = [];
    timeline.innerHTML = `<div class="note-empty">加载失败：${escapeHtml(err.message)}</div>`;
  }
}

function renderNoteTimeline() {
  const timeline = document.getElementById("noteTimeline");
  if (!state.sectorNotes.length) {
    timeline.innerHTML = '<div class="note-empty">还没有笔记，从今天开始记录。</div>';
    return;
  }
  timeline.innerHTML = state.sectorNotes.map((note) => `
    <article class="note-entry">
      <div class="note-entry-head">
        <div>
          <span class="note-entry-date">${formatNoteDate(note.date)}</span>
          <span class="note-entry-time">更新 ${formatTime(note.updated_at)}</span>
        </div>
        <div class="note-entry-actions">
          <button type="button" data-note-edit="${note.date}">编辑</button>
          <button type="button" class="note-delete" data-note-delete="${note.date}">删除</button>
        </div>
      </div>
      <div class="note-entry-content">${escapeHtml(note.content).replace(/\n/g, "<br>")}</div>
    </article>
  `).join("");
  timeline.querySelectorAll("[data-note-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById("noteDate").value = button.dataset.noteEdit;
      populateNoteEditor();
      document.getElementById("noteContent").focus();
    });
  });
  timeline.querySelectorAll("[data-note-delete]").forEach((button) => {
    button.addEventListener("click", () => deleteSectorNote(button.dataset.noteDelete));
  });
}

function populateNoteEditor() {
  const noteDate = document.getElementById("noteDate").value || localToday();
  const note = state.sectorNotes.find((item) => item.date === noteDate);
  document.getElementById("noteContent").value = note?.content || "";
  setNoteStatus(note ? "编辑该日期已有笔记" : "该日期尚未记录");
}

async function saveSectorNote() {
  const button = document.getElementById("noteSaveBtn");
  const noteDate = document.getElementById("noteDate").value;
  const content = document.getElementById("noteContent").value.trim();
  if (!noteDate || !content) {
    setNoteStatus("请选择日期并填写内容", true);
    return;
  }
  button.disabled = true;
  setNoteStatus("保存中...");
  try {
    const response = await fetch(`/api/sector-notes/${noteDate}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope: state.noteScope, content }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `${response.status}`);
    await loadSectorNotes(state.noteScope);
    document.getElementById("noteDate").value = noteDate;
    populateNoteEditor();
    setNoteStatus("已保存");
  } catch (err) {
    setNoteStatus(`保存失败：${err.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function deleteSectorNote(noteDate) {
  if (!window.confirm(`确定删除 ${state.noteScope} 在 ${noteDate} 的笔记吗？`)) {
    return;
  }
  try {
    const response = await fetch(
      `/api/sector-notes/${noteDate}?scope=${encodeURIComponent(state.noteScope)}`,
      { method: "DELETE" },
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `${response.status}`);
    await loadSectorNotes(state.noteScope);
    setNoteStatus("已删除");
  } catch (err) {
    setNoteStatus(`删除失败：${err.message}`, true);
  }
}

function setNoteStatus(message, isError = false) {
  const status = document.getElementById("noteStatus");
  status.textContent = message;
  status.className = isError ? "neg" : "muted";
}

function renderTable() {
  const starOnly = document.getElementById("starOnly").checked;
  const holdingOnly = document.getElementById("holdingOnly").checked;
  const actionableOnly = document.getElementById("actionableOnly").checked;
  const overheatOnly = document.getElementById("overheatOnly").checked;
  const query = document.getElementById("searchInput").value.trim();
  const rows = state.stocks.filter((stock) => {
    const stockGroups = stock.groups?.length ? stock.groups : [stock.group];
    if (state.group !== "全部") {
      const family = groupFamilies.find((item) => item.label === state.group);
      if (family && !stockGroups.some((group) => groupMatchesFamily(group, family))) return false;
      if (!family && !stockGroups.includes(state.group)) return false;
    }
    if (starOnly && !stock.star) return false;
    if (holdingOnly && !stock.holding) return false;
    if (actionableOnly && !actionableSignals.has(stock.signal.signal)) return false;
    if (overheatOnly && stock.signal.signal !== "过热不追") return false;
    if (query && !`${stock.code}${stock.name}`.includes(query)) return false;
    return true;
  }).sort(compareByCurrentSort);

  const body = document.getElementById("stockBody");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="16" class="empty">没有符合筛选条件的标的。</td></tr>`;
    return;
  }

  body.innerHTML = rows.map((stock) => stockRow(stock)).join("");
  renderSortHeaders();
  document.querySelectorAll("tr.stock-row").forEach((row) => {
    row.addEventListener("click", () => {
      state.expanded = state.expanded === row.dataset.code ? null : row.dataset.code;
      renderTable();
    });
  });
  const expandedStock = rows.find((stock) => stock.code === state.expanded);
  if (expandedStock) initializeStockNotePanel(expandedStock);
}

function renderSortHeaders() {
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    const active = th.dataset.sort === state.sort.key;
    th.classList.toggle("sorted", active);
    th.dataset.direction = active ? state.sort.direction : "";
  });
}

function compareByCurrentSort(a, b) {
  const direction = state.sort.direction === "asc" ? 1 : -1;
  const left = sortValue(a, state.sort.key);
  const right = sortValue(b, state.sort.key);
  const leftMissing = left === null || left === undefined || Number.isNaN(left);
  const rightMissing = right === null || right === undefined || Number.isNaN(right);
  if (leftMissing && rightMissing) return fallbackCompare(a, b);
  if (leftMissing) return 1;
  if (rightMissing) return -1;
  if (left > right) return direction;
  if (left < right) return -direction;
  return fallbackCompare(a, b);
}

function fallbackCompare(a, b) {
  return (b.signal?.rank_score || 0) - (a.signal?.rank_score || 0)
    || Number(b.star) - Number(a.star)
    || a.code.localeCompare(b.code);
}

function sortValue(stock, key) {
  const quote = stock.quote || {};
  const ind = stock.indicators || {};
  const signal = stock.signal || {};
  const values = {
    signal: signal.rank_score,
    price: stock.price,
    pct_chg: quote.pct_chg,
    return_5d: ind.return_5d,
    return_20d: ind.return_20d,
    amount: quote.amount,
    main_net_inflow: quote.main_net_inflow,
    rsi14: ind.rsi14,
    volume_ratio: ind.volume_ratio,
    dev_ma20: ind.dev_ma20,
    tier: stock.tier,
  };
  return values[key];
}

function defaultSortDirection(key) {
  return key === "tier" ? "asc" : "desc";
}

function stockRow(stock) {
  const pctChg = stock.quote?.pct_chg;
  const detail = state.expanded === stock.code ? detailRow(stock) : "";
  const stockGroups = stock.groups?.length ? stock.groups : [stock.group];
  const displayedGroup = state.group !== "全部" && stockGroups.includes(state.group)
    ? state.group
    : stock.group;
  const hiddenGroups = stockGroups.filter((group) => group !== displayedGroup);
  const groupTooltip = stockGroups.join(" / ");
  const hiddenGroupTooltip = hiddenGroups.join(" / ");
  return `
    <tr class="stock-row" data-code="${stock.code}">
      <td>
        <div class="stock-name"><button class="star-toggle ${stock.star ? "starred" : ""}" data-code="${stock.code}" title="${stock.star ? "取消星标" : "加星标"}" aria-label="${stock.star ? "取消星标" : "加星标"}">${stock.star ? "★" : "☆"}</button> ${holdingButton(stock)} ${stock.name}</div>
        <div class="stock-code-line">
          <button class="copy-code ${boardCodeClass(stock.code)}" data-code="${stock.code}" title="复制代码" aria-label="复制 ${stock.code}">${stock.code}</button>
          ${boardBadge(stock.code)}
          ${stock.watch ? '<span class="watch-mark">观察</span>' : ""}
        </div>
      </td>
      <td class="group-cell" title="${escapeHtml(groupTooltip)}">
        <span class="group-main">${escapeHtml(displayedGroup)}</span>${hiddenGroups.length ? `<span class="group-extra" title="${escapeHtml(hiddenGroupTooltip)}" aria-label="其他分组：${escapeHtml(hiddenGroupTooltip)}">另：${escapeHtml(hiddenGroupTooltip)}</span>` : ""}
      </td>
      <td>${tierBadge(stock.tier)}</td>
      <td>${formatPrice(stock.price)}</td>
      <td class="${numClass(pctChg)}">${formatPct(pctChg)}</td>
      <td class="${numClass(stock.indicators?.return_5d)}">${formatPct(stock.indicators?.return_5d)}</td>
      <td class="${numClass(stock.indicators?.return_20d)}">${formatPct(stock.indicators?.return_20d)}</td>
      <td>${sparklineSVG(stock.intraday, pctChg)}</td>
      <td>${formatMoney(stock.quote?.amount)}</td>
      <td class="${numClass(stock.quote?.main_net_inflow)}">${formatMoney(stock.quote?.main_net_inflow)}</td>
      <td>${maBlock(stock.indicators)}</td>
      <td>${formatNumber(stock.indicators?.rsi14, 1)}</td>
      <td>${formatNumber(stock.indicators?.volume_ratio, 2)}</td>
      <td>${signalPill(stock.signal.signal)}</td>
      <td class="signal-detail">${stock.signal.detail || ""}</td>
      <td>${stock.signal.action}</td>
    </tr>
    ${detail}
  `;
}

function stockBoard(code) {
  const value = String(code || "");
  if (value.startsWith("688") || value.startsWith("689")) {
    return { label: "科", name: "科创板", cls: "sci" };
  }
  if (value.startsWith("300") || value.startsWith("301") || value.startsWith("302")) {
    return { label: "创", name: "创业板", cls: "gem" };
  }
  return null;
}

function boardCodeClass(code) {
  return stockBoard(code) ? "restricted-board-code" : "";
}

function boardBadge(code) {
  const board = stockBoard(code);
  if (!board) return "";
  return `<span class="board-badge ${board.cls}" title="${board.name}，非主板权限需注意" aria-label="${board.name}">${board.label}</span>`;
}

function detailRow(stock) {
  const ind = stock.indicators || {};
  const signal = stock.signal || {};
  const stockGroups = stock.groups?.length ? stock.groups : [stock.group];
  return `
    <tr class="detail-row">
      <td colspan="16">
        <div class="detail">
          <section>
            <h3>触发原因</h3>
            <ul>${(signal.reasons || []).map((x) => `<li>${x}</li>`).join("")}</ul>
          </section>
          <section>
            <h3>下一触发</h3>
            <ul>${(signal.next_trigger || []).map((x) => `<li>${x}</li>`).join("")}</ul>
          </section>
          <section>
            <h3>关键指标</h3>
            <ul>
              <li>MA5 / 10 / 20 / 60：${formatPrice(ind.ma5)} / ${formatPrice(ind.ma10)} / ${formatPrice(ind.ma20)} / ${formatPrice(ind.ma60)}</li>
              <li>距20日高点：${formatPct(ind.from_high20)}</li>
              <li>距60日高点：${formatPct(ind.from_high60)}</li>
              <li>细分赛道：${stockGroups.join(" / ")}</li>
              <li>观察定位：${stock.note || "--"}</li>
              <li>数据状态：${stock.data_status}</li>
            </ul>
          </section>
          <section class="stock-note-panel" data-stock-note-code="${stock.code}">
            <div class="stock-note-heading">
              <div>
                <div class="notes-kicker">个股日志</div>
                <h3>${escapeHtml(stock.name)} <span class="muted">${stock.code}</span></h3>
              </div>
              <span class="muted">每日一条</span>
            </div>
            <div class="stock-note-workspace">
              <div class="stock-note-editor">
                <input class="note-date stock-note-date" type="date" value="${localToday()}" />
                <textarea
                  class="stock-note-content"
                  rows="4"
                  maxlength="20000"
                  placeholder="记录个股逻辑、买卖计划、关键价位和后续验证..."
                ></textarea>
                <div class="note-editor-actions">
                  <span class="stock-note-status muted"></span>
                  <button class="text-btn stock-note-today" type="button">今天</button>
                  <button class="text-btn primary stock-note-save" type="button">保存笔记</button>
                </div>
              </div>
              <div class="stock-note-timeline">
                <div class="note-empty">加载笔记...</div>
              </div>
            </div>
          </section>
        </div>
      </td>
    </tr>
  `;
}

function initializeStockNotePanel(stock) {
  const panel = document.querySelector(`[data-stock-note-code="${stock.code}"]`);
  if (!panel) return;
  panel.querySelector(".stock-note-date").addEventListener("change", () => {
    populateStockNoteEditor(stock, panel);
  });
  panel.querySelector(".stock-note-today").addEventListener("click", () => {
    panel.querySelector(".stock-note-date").value = localToday();
    populateStockNoteEditor(stock, panel);
  });
  panel.querySelector(".stock-note-save").addEventListener("click", () => {
    saveStockNote(stock, panel);
  });
  refreshStockNotes(stock, panel);
}

async function refreshStockNotes(stock, panel) {
  const timeline = panel.querySelector(".stock-note-timeline");
  timeline.innerHTML = '<div class="note-empty">加载笔记...</div>';
  try {
    const notes = await fetchJson(`/api/stock-notes?code=${stock.code}`);
    if (state.expanded !== stock.code || !panel.isConnected) return;
    state.stockNotes[stock.code] = notes;
    renderStockNoteTimeline(stock, panel);
    populateStockNoteEditor(stock, panel);
  } catch (err) {
    timeline.innerHTML = `<div class="note-empty">加载失败：${escapeHtml(err.message)}</div>`;
  }
}

function renderStockNoteTimeline(stock, panel) {
  const notes = state.stockNotes[stock.code] || [];
  const timeline = panel.querySelector(".stock-note-timeline");
  if (!notes.length) {
    timeline.innerHTML = '<div class="note-empty">还没有个股笔记。</div>';
    return;
  }
  timeline.innerHTML = notes.map((note) => `
    <article class="note-entry">
      <div class="note-entry-head">
        <div>
          <span class="note-entry-date">${formatNoteDate(note.date)}</span>
          <span class="note-entry-time">更新 ${formatTime(note.updated_at)}</span>
        </div>
        <div class="note-entry-actions">
          <button type="button" data-stock-note-edit="${note.date}">编辑</button>
          <button type="button" class="note-delete" data-stock-note-delete="${note.date}">删除</button>
        </div>
      </div>
      <div class="note-entry-content">${escapeHtml(note.content).replace(/\n/g, "<br>")}</div>
    </article>
  `).join("");
  timeline.querySelectorAll("[data-stock-note-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      panel.querySelector(".stock-note-date").value = button.dataset.stockNoteEdit;
      populateStockNoteEditor(stock, panel);
      panel.querySelector(".stock-note-content").focus();
    });
  });
  timeline.querySelectorAll("[data-stock-note-delete]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteStockNote(stock, panel, button.dataset.stockNoteDelete);
    });
  });
}

function populateStockNoteEditor(stock, panel) {
  const noteDate = panel.querySelector(".stock-note-date").value || localToday();
  const notes = state.stockNotes[stock.code] || [];
  const note = notes.find((item) => item.date === noteDate);
  panel.querySelector(".stock-note-content").value = note?.content || "";
  setStockNoteStatus(panel, note ? "编辑该日期已有笔记" : "该日期尚未记录");
}

async function saveStockNote(stock, panel) {
  const button = panel.querySelector(".stock-note-save");
  const noteDate = panel.querySelector(".stock-note-date").value;
  const content = panel.querySelector(".stock-note-content").value.trim();
  if (!noteDate || !content) {
    setStockNoteStatus(panel, "请选择日期并填写内容", true);
    return;
  }
  button.disabled = true;
  setStockNoteStatus(panel, "保存中...");
  try {
    const response = await fetch(`/api/stock-notes/${stock.code}/${noteDate}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `${response.status}`);
    await refreshStockNotes(stock, panel);
    panel.querySelector(".stock-note-date").value = noteDate;
    populateStockNoteEditor(stock, panel);
    setStockNoteStatus(panel, "已保存");
  } catch (err) {
    setStockNoteStatus(panel, `保存失败：${err.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function deleteStockNote(stock, panel, noteDate) {
  if (!window.confirm(`确定删除 ${stock.name} 在 ${noteDate} 的笔记吗？`)) {
    return;
  }
  try {
    const response = await fetch(`/api/stock-notes/${stock.code}/${noteDate}`, {
      method: "DELETE",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `${response.status}`);
    await refreshStockNotes(stock, panel);
    setStockNoteStatus(panel, "已删除");
  } catch (err) {
    setStockNoteStatus(panel, `删除失败：${err.message}`, true);
  }
}

function setStockNoteStatus(panel, message, isError = false) {
  const status = panel.querySelector(".stock-note-status");
  status.textContent = message;
  status.className = `stock-note-status ${isError ? "neg" : "muted"}`;
}

function maBlock(ind = {}) {
  return `
    <div class="ma-line">
      <span>MA5 ${formatPct(ind.dev_ma5)}</span>
      <span>MA20 ${formatPct(ind.dev_ma20)}</span>
    </div>
  `;
}

function signalPill(signal) {
  const cls = {
    "可试仓": "buy",
    "二次确认": "watch",
    "突破观察": "watch",
    "等回踩": "wait",
    "过热不追": "hot",
    "走弱剔除": "weak",
  }[signal] || "neutral";
  return `<span class="signal-pill ${cls}">${signal}</span>`;
}

function tierBadge(tier) {
  if (!tier) return '<span class="muted">--</span>';
  const cls = tier === 1 ? "t1" : tier === 2 ? "t2" : "t3";
  return `<span class="tier-badge ${cls}">T${tier}</span>`;
}

function localToday() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatNoteDate(value) {
  if (!value) return "--";
  const parsed = new Date(`${value}T00:00:00`);
  return parsed.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatTime(value) {
  if (!value) return "--";
  return value.replace("T", " ").slice(0, 19);
}

function formatPrice(value) {
  return value === null || value === undefined ? "--" : Number(value).toFixed(2);
}

function formatNumber(value, digits = 2) {
  return value === null || value === undefined ? "--" : Number(value).toFixed(digits);
}

function formatPct(value) {
  return value === null || value === undefined ? "--" : `${Number(value).toFixed(2)}%`;
}

function formatMoney(value) {
  if (value === null || value === undefined) return "--";
  const n = Number(value);
  if (Math.abs(n) >= 100000000) return `${(n / 100000000).toFixed(2)}亿`;
  if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(0)}万`;
  return n.toFixed(0);
}

function numClass(value) {
  if (value === null || value === undefined) return "";
  const n = Number(value);
  if (n > 0) return "pos";
  if (n < 0) return "neg";
  return "";
}

async function copyCode(code, button) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(code);
    } else {
      const input = document.createElement("textarea");
      input.value = code;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.left = "-9999px";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
    const original = button.textContent;
    button.textContent = "已复制";
    button.classList.add("copied");
    window.setTimeout(() => {
      button.textContent = original;
      button.classList.remove("copied");
    }, 900);
  } catch (error) {
    button.title = `复制失败：${error.message}`;
  }
}

async function toggleStar(code, button) {
  try {
    const res = await fetch("/api/toggle-star", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    const data = await res.json();
    // Update local state
    const stock = state.stocks.find((s) => s.code === code);
    if (stock) stock.star = data.star;
    // Update summary star count
    if (state.dashboard && state.dashboard.summary) {
      state.dashboard.summary.stars = state.stocks.filter((s) => s.star).length;
    }
    render();
  } catch (error) {
    button.title = `星标操作失败：${error.message}`;
  }
}

function holdingButton(stock) {
  return `<button class="holding-toggle ${stock.holding ? "active" : ""}" data-code="${stock.code}" title="${stock.holding ? "取消持仓" : "标记持仓"}" aria-label="${stock.holding ? "取消持仓" : "标记持仓"}">持</button>`;
}

async function toggleHolding(code, button) {
  try {
    const res = await fetch("/api/toggle-holding", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    const data = await res.json();
    const stock = state.stocks.find((item) => item.code === code);
    if (stock) stock.holding = data.holding;
    if (state.dashboard && state.dashboard.summary) {
      state.dashboard.summary.holdings = state.stocks.filter((item) => item.holding).length;
    }
    render();
  } catch (error) {
    button.title = `持仓操作失败：${error.message}`;
  }
}

async function toggleGroupStar(group, button) {
  try {
    const res = await fetch("/api/toggle-group-star", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group }),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    const data = await res.json();
    if (state.dashboard && state.dashboard.group_stats && state.dashboard.group_stats[group]) {
      state.dashboard.group_stats[group].star = data.star;
    }
    if (state.dashboard && state.dashboard.summary) {
      state.dashboard.summary.group_stars = Object.values(state.dashboard.group_stats || {})
        .filter((item) => item.star).length;
    }
    state.stocks.forEach((stock) => {
      const stockGroups = stock.groups?.length ? stock.groups : [stock.group];
      stock.group_star = stockGroups.some(
        (item) => state.dashboard?.group_stats?.[item]?.star,
      );
    });
    render();
  } catch (error) {
    button.title = `板块星标操作失败：${error.message}`;
  }
}

// ── Snapshots ──

async function openSnapshotPanel() {
  document.getElementById("snapshotOverlay").classList.remove("hidden");
  const listEl = document.getElementById("snapshotList");
  listEl.innerHTML = '<div class="empty">加载中…</div>';
  try {
    const snapshots = await fetchJson("/api/snapshots");
    if (!snapshots.length) {
      listEl.innerHTML = '<div class="empty">暂无历史快照。点击「刷新日K」时会自动生成快照。</div>';
      return;
    }
    listEl.innerHTML = snapshots.map((s) => {
      const sum = s.summary || {};
      const isActive = state.viewingSnapshot === s.id;
      return `
        <div class="snapshot-item ${isActive ? "active" : ""}" data-id="${s.id}">
          <div class="snapshot-time">${formatTime(s.created_at)}</div>
          <div class="snapshot-stats">
            <span>买点 ${sum.actionable ?? "--"}</span>
            <span>过热 ${sum.overheated ?? "--"}</span>
            <span>走弱 ${sum.weak ?? "--"}</span>
            <span>${s.stock_count}只</span>
          </div>
          <div class="snapshot-actions">
            <button class="snapshot-view-btn" data-id="${s.id}">${isActive ? "返回实时" : "查看"}</button>
            <button class="snapshot-delete-btn" data-id="${s.id}" data-created-at="${s.created_at}">删除</button>
          </div>
        </div>
      `;
    }).join("");
    // Bind click on view buttons
    listEl.querySelectorAll(".snapshot-view-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        loadSnapshotView(btn.dataset.id);
      });
    });
    listEl.querySelectorAll(".snapshot-delete-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteSnapshot(btn.dataset.id, btn.dataset.createdAt);
      });
    });
  } catch (err) {
    listEl.innerHTML = `<div class="empty">加载失败：${err.message}</div>`;
  }
}

async function deleteSnapshot(snapshotId, createdAt) {
  if (!window.confirm(`确定删除 ${formatTime(createdAt)} 的历史快照吗？此操作无法撤销。`)) {
    return;
  }
  try {
    const response = await fetch(`/api/snapshots/${snapshotId}`, { method: "DELETE" });
    if (!response.ok) throw new Error(`${response.status}`);
    if (state.viewingSnapshot === snapshotId) {
      state.viewingSnapshot = null;
      await loadData();
    }
    await openSnapshotPanel();
  } catch (err) {
    alert(`删除快照失败：${err.message}`);
  }
}

function closeSnapshotPanel() {
  document.getElementById("snapshotOverlay").classList.add("hidden");
}

async function loadSnapshotView(snapshotId) {
  try {
    if (state.viewingSnapshot === snapshotId) {
      // Exit snapshot view, reload live data
      state.viewingSnapshot = null;
      await loadData();
      closeSnapshotPanel();
      return;
    }
    const data = await fetchJson(`/api/snapshots/${snapshotId}`);
    state.viewingSnapshot = snapshotId;
    state.stocks = data.stocks || [];
    state.dashboard = {
      ...state.dashboard,
      summary: data.summary || {},
      group_stats: data.group_stats || {},
    };
    render();
    // Update header to show snapshot mode
    document.getElementById("lastUpdated").textContent = `快照：${formatTime(data.created_at)}（历史回放）`;
    closeSnapshotPanel();
  } catch (err) {
    alert(`加载快照失败：${err.message}`);
  }
}

// ── Sparkline ──

function sparklineSVG(prices, pctChg) {
  if (!prices || prices.length < 2) return '<span class="muted">--</span>';
  const w = 100, h = 30, padY = 3;
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  const step = w / (prices.length - 1);
  const points = prices.map((p, i) => {
    const x = i * step;
    const y = padY + (1 - (p - min) / range) * (h - 2 * padY);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const color = pctChg >= 0 ? "var(--red)" : "var(--green)";
  const fill = pctChg >= 0 ? "rgba(220,38,38,0.08)" : "rgba(21,128,61,0.08)";
  // Build area polygon (line + close to bottom)
  const areaPoints = points.join(" ")
    + ` ${w.toFixed(1)},${h.toFixed(1)} 0,${h.toFixed(1)}`;
  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">`
    + `<polygon points="${areaPoints}" fill="${fill}" />`
    + `<polyline points="${points.join(' ')}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" />`
    + `</svg>`;
}

function marketIndexSparklineSVG(prices, pctChg) {
  if (!prices || prices.length < 2) return '<span class="muted">--</span>';
  const w = 160, h = 42, padY = 4;
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  const step = w / (prices.length - 1);
  const points = prices.map((p, i) => {
    const x = i * step;
    const y = padY + (1 - (p - min) / range) * (h - 2 * padY);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const color = pctChg >= 0 ? "var(--red)" : "var(--green)";
  const fill = pctChg >= 0 ? "rgba(220,38,38,0.07)" : "rgba(21,128,61,0.07)";
  const areaPoints = points.join(" ")
    + ` ${w.toFixed(1)},${h.toFixed(1)} 0,${h.toFixed(1)}`;
  return `<svg class="market-sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">`
    + `<polygon points="${areaPoints}" fill="${fill}" />`
    + `<polyline points="${points.join(' ')}" fill="none" stroke="${color}" stroke-width="1.7" stroke-linejoin="round" />`
    + `</svg>`;
}
