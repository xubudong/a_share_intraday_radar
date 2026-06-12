const state = {
  dashboard: null,
  stocks: [],
  group: "全部",
  expanded: null,
  timer: null,
  refreshPollTimer: null,
  sort: { key: "signal", direction: "desc" },
  viewingSnapshot: null,  // snapshot ID or null for live
};

const actionableSignals = new Set(["可试仓", "二次确认", "突破观察"]);

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
  ["starOnly", "actionableOnly", "overheatOnly"].forEach((id) => {
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
  const el = document.getElementById("radarList");
  if (!radar.length) {
    el.innerHTML = `<div class="empty">当前没有进入买点雷达的标的。</div>`;
    return;
  }
  el.innerHTML = radar.map((stock) => `
    <article class="radar-card">
      <div class="radar-title">
        <span>${stock.star ? '<button class="star-toggle starred" data-code="' + stock.code + '" title="取消星标" aria-label="取消星标">★</button> ' : '<button class="star-toggle" data-code="' + stock.code + '" title="加星标" aria-label="加星标">☆</button> '}${stock.name}</span>
        ${signalPill(stock.signal.signal)}
      </div>
      <div class="stock-code">${stock.code} · ${stock.group}</div>
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

function renderGroups() {
  const groupStats = (state.dashboard && state.dashboard.group_stats) || {};
  const allGroups = Array.from(new Set(
    state.stocks.flatMap((stock) => stock.groups?.length ? stock.groups : [stock.group])
  ));
  const groupFamilies = [
    { prefix: "化工-", label: "化工" },
    { prefix: "有色-", label: "有色" },
    { prefix: "半导体芯片-", label: "芯片" },
    { prefix: "光模块-", label: "光模块" },
    { prefix: "半导体材料-", label: "半导体材料" },
  ];
  const focusPrefixes = groupFamilies.map((family) => family.prefix);
  const otherGroups = allGroups
    .filter((group) => !focusPrefixes.some((prefix) => group.startsWith(prefix)))
    .sort();
  const groups = ["全部", ...allGroups];
  if (!groups.includes(state.group)) state.group = "全部";

  const groupButton = (group, display = group) => {
    const gs = groupStats[group] || {};
    const avg = gs.avg_pct;
    const avgTag = avg === undefined || avg === null
      ? '<span class="group-pct muted">--</span>'
      : `<span class="group-pct ${avg > 0 ? 'pos' : avg < 0 ? 'neg' : 'muted'}">${avg >= 0 ? '+' : ''}${avg.toFixed(2)}%</span>`;
    return `<button class="${group === state.group ? "active" : ""}" data-group="${group}" title="${group}">${display}${avgTag}</button>`;
  };

  let html = groupButton("全部");
  for (const family of groupFamilies) {
    const familyGroups = allGroups
      .filter((group) => group.startsWith(family.prefix))
      .sort();
    if (!familyGroups.length) continue;
    html += `<div class="group-cluster"><span class="group-cluster-label">${family.label}</span>`;
    html += familyGroups
      .map((group) => groupButton(group, group.slice(family.prefix.length)))
      .join("");
    html += "</div>";
  }
  if (otherGroups.length) {
    html += '<div class="group-cluster"><span class="group-cluster-label">其他</span>';
    html += otherGroups.map((group) => groupButton(group)).join("");
    html += "</div>";
  }

  document.getElementById("groupFilter").innerHTML = html;
  document.querySelectorAll("#groupFilter button").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.group = btn.dataset.group;
      renderGroups();
      renderTable();
    });
  });
}

function renderTable() {
  const starOnly = document.getElementById("starOnly").checked;
  const actionableOnly = document.getElementById("actionableOnly").checked;
  const overheatOnly = document.getElementById("overheatOnly").checked;
  const query = document.getElementById("searchInput").value.trim();
  const rows = state.stocks.filter((stock) => {
    const stockGroups = stock.groups?.length ? stock.groups : [stock.group];
    if (state.group !== "全部" && !stockGroups.includes(state.group)) return false;
    if (starOnly && !stock.star) return false;
    if (actionableOnly && !actionableSignals.has(stock.signal.signal)) return false;
    if (overheatOnly && stock.signal.signal !== "过热不追") return false;
    if (query && !`${stock.code}${stock.name}`.includes(query)) return false;
    return true;
  }).sort(compareByCurrentSort);

  const body = document.getElementById("stockBody");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="14" class="empty">没有符合筛选条件的标的。</td></tr>`;
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
  const extraGroupCount = Math.max(0, stockGroups.length - 1);
  return `
    <tr class="stock-row" data-code="${stock.code}">
      <td>
        <div class="stock-name"><button class="star-toggle ${stock.star ? "starred" : ""}" data-code="${stock.code}" title="${stock.star ? "取消星标" : "加星标"}" aria-label="${stock.star ? "取消星标" : "加星标"}">${stock.star ? "★" : "☆"}</button> ${stock.name}</div>
        <div class="stock-code-line">
          <button class="copy-code" data-code="${stock.code}" title="复制代码" aria-label="复制 ${stock.code}">${stock.code}</button>
          ${stock.watch ? '<span class="watch-mark">观察</span>' : ""}
        </div>
      </td>
      <td title="${stockGroups.join(" / ")}">${displayedGroup}${extraGroupCount ? ` <span class="muted">+${extraGroupCount}</span>` : ""}</td>
      <td>${tierBadge(stock.tier)}</td>
      <td>${formatPrice(stock.price)}</td>
      <td class="${numClass(pctChg)}">${formatPct(pctChg)}</td>
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

function detailRow(stock) {
  const ind = stock.indicators || {};
  const signal = stock.signal || {};
  const stockGroups = stock.groups?.length ? stock.groups : [stock.group];
  return `
    <tr class="detail-row">
      <td colspan="14">
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
        </div>
      </td>
    </tr>
  `;
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
    state.dashboard = { ...state.dashboard, summary: data.summary || {} };
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
