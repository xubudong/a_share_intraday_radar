const marketState = {
  payload: null,
  timer: null,
  source: "全部",
  sectionCollapsed: {},
};

document.addEventListener("DOMContentLoaded", () => {
  bindMarketEvents();
  document.getElementById("sentimentDate").value = localToday();
  loadSentiment();
});

function bindMarketEvents() {
  document.getElementById("sentimentLoadBtn").addEventListener("click", loadSentiment);
  document.getElementById("sentimentRefreshBtn").addEventListener("click", refreshSentiment);
  document.getElementById("sentimentDate").addEventListener("change", loadSentiment);
  document.getElementById("markedOnly").addEventListener("change", renderMarketContent);
  document.getElementById("matchedOnly").addEventListener("change", renderMarketContent);
  document.getElementById("marketSearch").addEventListener("input", renderMarketContent);
  document.getElementById("expandAllSections").addEventListener("click", () => setAllSectionsCollapsed(false));
  document.getElementById("collapseAllSections").addEventListener("click", () => setAllSectionsCollapsed(true));
  document.getElementById("sourceFilter").addEventListener("change", (event) => {
    marketState.source = event.target.value;
    renderMarketContent();
  });
  document.addEventListener("click", (event) => {
    const sectionToggle = event.target.closest(".section-toggle");
    if (sectionToggle) {
      const name = sectionToggle.dataset.sectionName;
      marketState.sectionCollapsed[name] = !marketState.sectionCollapsed[name];
      renderSections();
      return;
    }
    const markBtn = event.target.closest(".market-mark-btn");
    if (markBtn) {
      toggleMarketMark(markBtn.dataset.itemId);
      return;
    }
    const rawBtn = event.target.closest(".raw-toggle");
    if (rawBtn) {
      const card = rawBtn.closest(".timeline-item");
      const raw = card.querySelector(".timeline-raw");
      raw.classList.toggle("hidden");
      rawBtn.textContent = raw.classList.contains("hidden") ? "原始字段" : "收起";
    }
  });
}

async function loadSentiment() {
  setMarketBusy(true);
  window.clearTimeout(marketState.timer);
  try {
    const date = document.getElementById("sentimentDate").value || localToday();
    marketState.payload = await fetchJson(`/api/sentiment?date=${encodeURIComponent(date)}`);
    renderMarket();
    if (marketState.payload.refresh?.refreshing) schedulePoll();
  } catch (error) {
    renderMarketError(error);
  } finally {
    setMarketBusy(false);
  }
}

async function refreshSentiment() {
  setMarketBusy(true);
  try {
    const date = document.getElementById("sentimentDate").value || localToday();
    const status = await fetchJson(
      `/api/sentiment/refresh?date=${encodeURIComponent(date)}&profile=fast&include_telegraph=false`,
      { method: "POST" },
    );
    marketState.payload = {
      ...(marketState.payload || {}),
      refresh: status,
    };
    renderHeader();
    schedulePoll();
  } catch (error) {
    renderMarketError(error);
    setMarketBusy(false);
  }
}

function schedulePoll() {
  window.clearTimeout(marketState.timer);
  marketState.timer = window.setTimeout(pollSentiment, 1500);
}

async function pollSentiment() {
  try {
    const date = document.getElementById("sentimentDate").value || localToday();
    marketState.payload = await fetchJson(`/api/sentiment?date=${encodeURIComponent(date)}`);
    renderMarket();
    if (marketState.payload.refresh?.refreshing) {
      schedulePoll();
      return;
    }
  } catch (error) {
    renderMarketError(error);
  }
  setMarketBusy(false);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `${response.status}`);
  return data;
}

function setMarketBusy(busy) {
  document.getElementById("sentimentRefreshBtn").disabled = busy;
  document.getElementById("sentimentLoadBtn").disabled = busy;
  document.getElementById("sentimentRefreshBtn").textContent = busy ? "刷新中..." : "刷新舆情";
}

function renderMarket() {
  renderHeader();
  renderSummary();
  renderSourceFilter();
  syncSectionState();
  renderMarketContent();
  renderSourceSummary();
}

function renderMarketContent() {
  renderSections();
  renderTimeline();
}

function renderHeader() {
  const payload = marketState.payload || {};
  const status = document.getElementById("marketStatus");
  const refresh = payload.refresh || {};
  if (refresh.refreshing) {
    status.textContent = refresh.pending ? "排队刷新" : "刷新中";
    status.className = "badge neutral";
  } else if (payload.status === "ok") {
    status.textContent = "已生成";
    status.className = "badge open";
  } else {
    status.textContent = "无缓存";
    status.className = "badge closed";
  }
  document.getElementById("marketUpdated").textContent = `生成：${formatTime(payload.generated_at)}`;
  const summary = payload.summary || {};
  const errors = summary.error_count || 0;
  document.getElementById("marketSourceStatus").textContent = refresh.refreshing
    ? "来源：后台采集中"
    : errors
      ? `来源：部分异常 ${errors} 个`
      : payload.status === "ok"
        ? "来源：已读取"
        : "来源：尚无缓存";
}

function renderSummary() {
  const summary = (marketState.payload && marketState.payload.summary) || {};
  const items = [
    ["新闻", summary.timeline_count ?? 0],
    ["重点", summary.manual_marked ?? 0],
    ["命中股票池", summary.auto_matched ?? 0],
    ["来源", summary.source_count ?? 0],
    ["异常", summary.error_count ?? 0],
  ];
  document.getElementById("marketSummary").innerHTML = items.map(([label, value]) => `
    <div class="summary-item">
      <div class="summary-label">${label}</div>
      <div class="summary-value">${value}</div>
    </div>
  `).join("");
}

function renderSourceFilter() {
  const current = marketState.source;
  const sources = Array.from(new Map(
    ((marketState.payload && marketState.payload.timeline) || [])
      .map((item) => [item.source, item.source_label || item.source])
  ).entries());
  const options = [['全部', '全部来源'], ...sources];
  const select = document.getElementById("sourceFilter");
  select.innerHTML = options
    .map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`)
    .join("");
  marketState.source = options.some(([value]) => value === current) ? current : "全部";
  select.value = marketState.source;
}

function renderSections() {
  const sections = (marketState.payload && marketState.payload.market_sections) || [];
  const query = currentSearchQuery();
  const matchedOnly = document.getElementById("matchedOnly").checked;
  const filteredSections = sections.map((section) => ({
    ...section,
    items: (section.items || []).filter((item) => sectionItemFilter(item, query, matchedOnly)),
    raw_count: (section.items || []).length,
  }));
  const visibleCount = filteredSections.reduce((sum, section) => sum + section.items.length, 0);
  const rawCount = filteredSections.reduce((sum, section) => sum + section.raw_count, 0);
  document.getElementById("marketSectionCount").textContent = `${sections.length} 组 · ${visibleCount} / ${rawCount} 条`;
  const root = document.getElementById("marketSections");
  if (!sections.length) {
    root.innerHTML = '<div class="empty">暂无情绪或主线材料。</div>';
    return;
  }
  root.innerHTML = filteredSections.map((section) => {
    const collapsed = Boolean(marketState.sectionCollapsed[section.name]);
    return `
    <section class="market-section ${collapsed ? "collapsed" : ""}">
      <div class="market-section-head">
        <h3>${escapeHtml(section.title)}</h3>
        <button class="section-toggle" type="button" data-section-name="${escapeHtml(section.name)}" aria-expanded="${String(!collapsed)}">
          ${collapsed ? "展开" : "折叠"} · ${section.items.length}/${section.raw_count}
        </button>
      </div>
      <div class="market-section-items">
        ${section.items.length ? section.items.map((item) => `
          <article class="market-section-item ${item.auto_matched ? "auto-hit" : ""}">
            ${renderFormattedText(item.text || "", item, { boldPrefix: true })}
            ${matchTags(item)}
          </article>
        `).join("") : '<div class="empty compact-empty">没有符合筛选条件的内容。</div>'}
      </div>
    </section>
  `;
  }).join("");
}

function renderSourceSummary() {
  const sources = (marketState.payload && marketState.payload.source_summary) || [];
  const root = document.getElementById("sourceSummary");
  if (!sources.length) {
    root.innerHTML = '<div class="empty">暂无来源状态。</div>';
    return;
  }
  root.innerHTML = sources.map((source) => `
    <div class="source-row ${source.status === "ok" ? "ok" : "bad"}">
      <div>
        <strong>${escapeHtml(source.name)}</strong>
        <span>${source.status}</span>
      </div>
      <div class="muted">${source.item_count ?? 0} 条 · ${source.elapsed_sec ?? 0}s · ${source.attempts ?? 1} 次</div>
      ${source.error ? `<div class="source-error">${escapeHtml(source.error)}</div>` : ""}
    </div>
  `).join("");
}

function renderTimeline() {
  const allItems = (marketState.payload && marketState.payload.timeline) || [];
  const filtered = allItems.filter(timelineFilter);
  document.getElementById("timelineCount").textContent = `${filtered.length} / ${allItems.length} 条`;
  const root = document.getElementById("timelineList");
  if (!filtered.length) {
    root.innerHTML = marketState.payload?.status === "missing"
      ? '<div class="empty">该日期暂无缓存，点击“刷新舆情”采集。</div>'
      : '<div class="empty">没有符合筛选条件的新闻。</div>';
    return;
  }
  root.innerHTML = filtered.map((item) => `
    <article class="timeline-item ${item.manual_marked ? "marked" : ""} ${item.auto_matched ? "auto-hit" : ""}">
      <div class="timeline-stem">
        <span></span>
      </div>
      <div class="timeline-card">
        <div class="timeline-head">
          <div>
            <span class="timeline-time">${formatTime(item.published_at)}</span>
            <span class="timeline-source">${escapeHtml(item.source_label || item.source)}</span>
            ${importanceBadge(item)}
            ${duplicateBadge(item)}
          </div>
          <div class="timeline-actions">
            <button class="raw-toggle" type="button">原始字段</button>
            <button
              class="market-mark-btn ${item.manual_marked ? "active" : ""}"
              type="button"
              data-item-id="${escapeHtml(item.id)}"
            >${item.manual_marked ? "已重点" : "重点"}</button>
          </div>
        </div>
        ${item.title ? `<h3>${renderInlineText(item.title, item, { boldPrefix: true })}</h3>` : ""}
        ${item.content ? `<div class="timeline-content">${renderFormattedText(item.content, item)}</div>` : ""}
        ${matchTags(item)}
        <pre class="timeline-raw hidden">${escapeHtml(JSON.stringify(item.raw || {}, null, 2))}</pre>
      </div>
    </article>
  `).join("");
}

function timelineFilter(item) {
  if (document.getElementById("markedOnly").checked && !item.manual_marked) return false;
  if (document.getElementById("matchedOnly").checked && !item.auto_matched) return false;
  if (marketState.source !== "全部" && item.source !== marketState.source) return false;
  const query = currentSearchQuery();
  if (!query) return true;
  const stockText = (item.matched_stocks || []).map((stock) => `${stock.code} ${stock.name}`).join(" ");
  const groupText = (item.matched_groups || []).join(" ");
  const text = [
    item.title,
    item.content,
    item.source_label,
    stockText,
    groupText,
    (item.match_reasons || []).join(" "),
  ].join(" ").toLowerCase();
  return text.includes(query);
}

function sectionItemFilter(item, query, matchedOnly) {
  if (matchedOnly && !item.auto_matched) return false;
  if (!query) return true;
  const stockText = (item.matched_stocks || []).map((stock) => `${stock.code} ${stock.name}`).join(" ");
  const groupText = (item.matched_groups || []).join(" ");
  const text = [
    item.text,
    stockText,
    groupText,
    (item.match_reasons || []).join(" "),
  ].join(" ").toLowerCase();
  return text.includes(query);
}

function currentSearchQuery() {
  return document.getElementById("marketSearch").value.trim().toLowerCase();
}

function syncSectionState() {
  const sections = (marketState.payload && marketState.payload.market_sections) || [];
  const names = new Set(sections.map((section) => section.name));
  Object.keys(marketState.sectionCollapsed).forEach((name) => {
    if (!names.has(name)) delete marketState.sectionCollapsed[name];
  });
  sections.forEach((section) => {
    if (!(section.name in marketState.sectionCollapsed)) {
      marketState.sectionCollapsed[section.name] = false;
    }
  });
}

function setAllSectionsCollapsed(collapsed) {
  const sections = (marketState.payload && marketState.payload.market_sections) || [];
  sections.forEach((section) => {
    marketState.sectionCollapsed[section.name] = collapsed;
  });
  renderSections();
}

function matchTags(item) {
  const stocks = item.matched_stocks || [];
  const groups = item.matched_groups || [];
  const reasons = item.match_reasons || [];
  if (!stocks.length && !groups.length) return "";
  return `
    <div class="match-tags">
      ${stocks.slice(0, 8).map((stock) => `
        <span class="match-tag stock" title="${escapeHtml((stock.groups || []).join(" / "))}">
          ${escapeHtml(stock.name)} ${escapeHtml(stock.code)}
        </span>
      `).join("")}
      ${groups.slice(0, 8).map((group) => `<span class="match-tag group">${escapeHtml(group)}</span>`).join("")}
      ${reasons.length ? `<span class="match-reason">${escapeHtml(reasons.slice(0, 3).join("；"))}</span>` : ""}
    </div>
  `;
}

function importanceBadge(item) {
  if (item.importance_score === null || item.importance_score === undefined) return "";
  const cls = Number(item.importance_score) >= 3 ? "high" : Number(item.importance_score) === 2 ? "mid" : "low";
  const label = item.importance_label || "重要度";
  return `<span class="importance-badge ${cls}" title="华尔街见闻原始 score 字段">${escapeHtml(label)} ${escapeHtml(item.importance_score)}</span>`;
}

function duplicateBadge(item) {
  const count = Number(item.duplicate_count || 0);
  if (count <= 1) return "";
  const sources = (item.duplicate_sources || []).join(" / ");
  return `<span class="duplicate-badge" title="${escapeHtml(sources)}">重复源 ${count}</span>`;
}

function renderFormattedText(value, item = {}, options = {}) {
  const lines = splitFormattedLines(String(value || ""));
  if (!lines.length) return "";
  return `<div class="formatted-text">${
    lines.map((line) => `<div>${renderInlineText(line, item, options)}</div>`).join("")
  }</div>`;
}

function splitFormattedLines(value) {
  const text = String(value || "").trim();
  if (!text) return [];
  if (/\r?\n/.test(text)) {
    return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  }
  let normalized = text
    .replace(/([；;])\s*/g, "$1\n")
    .replace(/([。])\s*/g, "$1\n")
    .replace(/\s*(\d+\.)\s*/g, "\n$1 ");
  const colonIndex = firstColonIndex(normalized);
  if (colonIndex > 0 && !normalized.slice(0, colonIndex).includes("\n")) {
    const head = normalized.slice(0, colonIndex + 1);
    const tail = normalized.slice(colonIndex + 1).trim();
    if (tail) normalized = `${head}\n${tail}`;
  }
  return normalized.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

function renderInlineText(value, item = {}, options = {}) {
  const text = String(value || "");
  if (!text) return "";
  if (options.boldPrefix) {
    const index = firstColonIndex(text);
    if (index > 0) {
      const head = text.slice(0, index);
      const sep = text[index];
      const tail = text.slice(index + 1);
      return `<strong>${highlightStockTerms(head, item)}</strong>${escapeHtml(sep)}${highlightStockTerms(tail, item)}`;
    }
  }
  return highlightStockTerms(text, item);
}

function firstColonIndex(value) {
  const cn = value.indexOf("：");
  const en = value.indexOf(":");
  if (cn < 0) return en;
  if (en < 0) return cn;
  return Math.min(cn, en);
}

function highlightStockTerms(value, item = {}) {
  let html = escapeHtml(value);
  const terms = [];
  (item.matched_stocks || []).forEach((stock) => {
    if (stock.name) terms.push(stock.name);
    if (stock.code) terms.push(stock.code);
  });
  Array.from(new Set(terms))
    .filter((term) => String(term).length >= 2)
    .sort((a, b) => String(b).length - String(a).length)
    .forEach((term) => {
      const escaped = escapeHtml(term);
      html = html.replace(new RegExp(escapeRegExp(escaped), "g"), `<strong>${escaped}</strong>`);
    });
  return html;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function toggleMarketMark(itemId) {
  try {
    const data = await fetchJson(`/api/sentiment/marks/${encodeURIComponent(itemId)}/toggle`, {
      method: "POST",
    });
    const item = (marketState.payload.timeline || []).find((current) => current.id === itemId);
    if (item) item.manual_marked = data.manual_marked;
    if (marketState.payload.summary) {
      marketState.payload.summary.manual_marked = marketState.payload.timeline
        .filter((current) => current.manual_marked).length;
    }
    renderSummary();
    renderTimeline();
  } catch (error) {
    alert(`标记失败：${error.message}`);
  }
}

function renderMarketError(error) {
  document.getElementById("marketStatus").textContent = "异常";
  document.getElementById("marketStatus").className = "badge closed";
  document.getElementById("marketSourceStatus").textContent = `错误：${error.message}`;
}

function localToday() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatTime(value) {
  if (!value) return "--";
  return String(value).replace("T", " ").slice(0, 19);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
