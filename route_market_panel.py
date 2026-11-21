"""HTML for the FX route and destination-market tracker."""

import json


PANEL = """
<section class="panel rmt-panel" id="route-market-panel" aria-labelledby="rmt-title">
  <div class="rmt-heading">
    <h2 id="rmt-title">债券还是股票？</h2>
    <div class="rmt-period" role="group" aria-label="汇率观察周期">
      <button type="button" data-rmt-period="daily" aria-pressed="false">日度</button>
      <button type="button" data-rmt-period="weekly" aria-pressed="true">周度</button>
    </div>
  </div>
  <p class="rmt-note">选一条 3B 汇率路径，查看终点市场偏债还是偏股。</p>
  <div class="rmt-toolbar">
    <div class="rmt-triads" role="group" aria-label="三币种组合">
      <button type="button" data-rmt-group="JP" aria-pressed="true">中日美</button>
      <button type="button" data-rmt-group="DE" aria-pressed="false">中德美</button>
      <button type="button" data-rmt-group="RU" aria-pressed="false">中俄美</button>
    </div>
    <label for="rmt-window">汇率日期 <select id="rmt-window"></select></label>
  </div>
  <div class="rmt-routes" id="rmt-routes" role="group" aria-label="有向汇率路径"></div>
  <p class="rmt-sr" id="rmt-announcement" role="status"></p>
  <div id="rmt-empty" class="rmt-empty" hidden>所选周期暂无共同收盘数据。</div>
  <article id="rmt-verdict" class="rmt-verdict" aria-labelledby="rmt-verdict-title" hidden>
    <div class="rmt-verdict-top">
      <span id="rmt-verdict-market"></span>
      <span id="rmt-verdict-badge" class="rmt-badge"></span>
    </div>
    <h3 id="rmt-verdict-title" tabindex="-1"></h3>
    <p id="rmt-verdict-explanation"></p>
    <dl id="rmt-verdict-values" class="rmt-verdict-values"></dl>
    <div id="rmt-verdict-reference" class="rmt-verdict-reference" hidden>
      <span id="rmt-verdict-date"></span>
      <a id="rmt-verdict-source" target="_blank" rel="noopener noreferrer" hidden></a>
    </div>
    <button id="rmt-history-button" class="rmt-history-button" type="button" hidden>
      <span>看最近有结果</span><span id="rmt-history-preview"></span>
    </button>
  </article>
  <details id="rmt-evidence" class="rmt-evidence" hidden>
    <summary>查看依据</summary>
    <p class="rmt-note">箭头表示汇率比较顺序。债券和股指按后续收盘观察，实际净买入按官方统计周显示。</p>
  <div class="rmt-stages" id="rmt-stages" hidden>
    <article class="rmt-card" aria-labelledby="rmt-fx-title">
      <h3 id="rmt-fx-title">汇率方向</h3>
      <p class="rmt-period-note" id="rmt-fx-dates"></p>
      <p class="rmt-fx-display" id="rmt-fx-direction"></p>
      <dl class="rmt-inline-values" id="rmt-fx-values"></dl>
    </article>
    <article class="rmt-card" aria-labelledby="rmt-bond-title">
      <h3 id="rmt-bond-title">终点市场债券</h3>
      <p class="rmt-period-note" id="rmt-bond-dates"></p>
      <table class="rmt-table">
        <thead><tr><th scope="col">期限</th><th scope="col">收益率</th><th scope="col">变动</th></tr></thead>
        <tbody id="rmt-bond-rows"></tbody>
      </table>
    </article>
    <article class="rmt-card" aria-labelledby="rmt-equity-title">
      <h3 id="rmt-equity-title">终点市场股指</h3>
      <p class="rmt-period-note" id="rmt-equity-base"></p>
      <table class="rmt-table">
        <thead><tr><th scope="col">后续收盘</th><th scope="col">日期</th><th scope="col">涨跌</th></tr></thead>
        <tbody id="rmt-equity-rows"></tbody>
      </table>
    </article>
  </div>
  <aside class="rmt-flow" id="rmt-flow" aria-labelledby="rmt-flow-title" hidden>
    <div class="rmt-flow-heading">
      <h3 id="rmt-flow-title">实际净买入</h3>
      <span id="rmt-flow-status" class="rmt-badge"></span>
    </div>
    <p class="rmt-period-note" id="rmt-flow-dates"></p>
    <dl class="rmt-flow-values" id="rmt-flow-values"></dl>
    <p class="rmt-note rmt-flow-note"><span id="rmt-flow-detail"></span> <a id="rmt-flow-source" hidden target="_blank" rel="noopener noreferrer"></a></p>
  </aside>
  </details>
  <noscript><p class="rmt-note">启用 JavaScript 后可切换路径和观察日期。</p></noscript>
</section>
"""

STYLES = """
<style>
.rmt-panel { scroll-margin-top: 12px; }
.rmt-panel h2, .rmt-panel h3, .rmt-panel p { margin: 0; }
.rmt-heading, .rmt-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.rmt-toolbar { justify-content: flex-start; margin-top: 12px; }
.rmt-toolbar label { display: inline-flex; gap: 6px; align-items: center; color: var(--muted); font-size: 12px; white-space: nowrap; }
.rmt-triads, .rmt-period, .rmt-routes { display: flex; flex-wrap: wrap; gap: 5px; }
.rmt-panel :is(button, select) { min-height: 32px; font: inherit; font-size: 12px; font-weight: 600; color: var(--ink); background: #fff; border: 1px solid var(--line); border-radius: 6px; padding: 4px 10px; }
.rmt-panel button { cursor: pointer; }
.rmt-panel button:hover { border-color: #aac5ee; background: #f7f9fc; }
.rmt-panel button[aria-pressed="true"] { background: #eaf2ff; border-color: #aac5ee; color: var(--blue); }
.rmt-panel :is(button, select, a, summary):focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.rmt-panel select:disabled { opacity: .6; }
.rmt-routes { margin-top: 9px; }
.rmt-routes button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; }
.rmt-routes small { font-size: 9px; font-weight: 700; color: var(--blue); }
.rmt-panel .rmt-note { color: var(--muted); font-size: 12px; line-height: 1.45; margin-top: 8px; }
.rmt-verdict { margin-top: 12px; padding: 14px 16px; border: 1px solid var(--line); border-left: 4px solid #94a3b8; border-radius: 8px; background: #f8fafc; }
.rmt-verdict[data-kind="official"] { border-left-color: #16803a; background: #f3faf5; }
.rmt-verdict[data-kind="price"] { border-left-color: var(--blue); background: #f4f8ff; }
.rmt-verdict-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--muted); font-size: 12px; }
.rmt-panel #rmt-verdict-title { margin: 5px 0; font-size: clamp(19px, 3vw, 24px); line-height: 1.25; }
.rmt-panel #rmt-verdict-explanation { font-size: 13px; color: var(--ink); line-height: 1.6; }
.rmt-panel .rmt-verdict-values { display: flex; flex-wrap: wrap; gap: 5px 18px; font-size: 13px; margin-top: 7px; }
.rmt-verdict-values:empty { display: none; }
.rmt-verdict-values > div { display: flex; align-items: baseline; gap: 6px; }
.rmt-verdict-values dd { overflow-wrap: anywhere; }
.rmt-verdict-reference { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 7px; color: var(--muted); font-size: 12px; }
.rmt-verdict-reference a { color: var(--blue); }
.rmt-panel .rmt-history-button { display: flex; align-items: baseline; text-align: left; flex-wrap: wrap; column-gap: 8px; row-gap: 2px; margin-top: 9px; color: var(--blue); background: #fff; }
.rmt-history-button #rmt-history-preview { color: var(--muted); font-weight: 500; }
.rmt-panel .rmt-history-button:hover { background: #eaf2ff; }
.rmt-evidence { margin-top: 10px; }
.rmt-evidence summary { cursor: pointer; width: fit-content; color: var(--blue); font-size: 13px; font-weight: 650; padding: 4px; border-radius: 3px; }
.rmt-stages { display: grid; grid-template-columns: minmax(170px, .85fr) minmax(225px, 1.2fr) minmax(185px, .95fr); gap: 8px; margin-top: 10px; }
.rmt-panel [hidden] { display: none; }
.rmt-card, .rmt-flow, .rmt-empty { border: 1px solid var(--line); border-radius: 7px; padding: 10px 12px; min-width: 0; }
.rmt-card h3, .rmt-flow h3 { font-size: 13px; font-weight: 750; }
.rmt-panel .rmt-period-note { color: var(--muted); margin: 4px 0 7px; font-size: 11px; min-height: 1.4em; font-variant-numeric: tabular-nums; }
.rmt-panel .rmt-fx-display { margin: 9px 0; font-size: 15px; font-weight: 750; }
.rmt-panel dl, .rmt-panel dd { margin: 0; }
.rmt-inline-values { display: grid; row-gap: 4px; font-size: 12px; }
.rmt-inline-values > div { display: flex; justify-content: space-between; gap: 10px; }
.rmt-panel dt { color: var(--muted); }
.rmt-panel dd { font-weight: 680; font-variant-numeric: tabular-nums; }
.rmt-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
.rmt-table :is(th, td) { padding: 4px 0 4px 6px; text-align: right; border-bottom: 1px solid var(--line); }
.rmt-table th:first-child { text-align: left; padding-left: 0; }
.rmt-table thead th, .rmt-table small { color: var(--muted); font-size: 11px; }
.rmt-table small { font-weight: 400; display: block; overflow-wrap: anywhere; }
.rmt-table tbody tr:last-child :is(th, td) { border-bottom: 0; }
.rmt-table tbody td:last-child { font-weight: 650; white-space: nowrap; }
.rmt-value-up { color: var(--pos); }
.rmt-value-down { color: var(--neg); }
.rmt-flow, .rmt-empty { background: #f8fafc; margin-top: 8px; }
.rmt-flow-heading { display: flex; gap: 8px; align-items: center; }
.rmt-badge { padding: 1px 7px; border: 1px solid var(--line); border-radius: 100px; background: #fff; color: var(--muted); font-size: 11px; font-weight: 650; }
.rmt-badge[data-state="published"] { color: #166534; background: #f0fdf4; border-color: #bbf7d0; }
.rmt-badge[data-state="pending"] { color: #92400e; background: #fffbeb; border-color: #fde68a; }
.rmt-flow-values { display: flex; flex-wrap: wrap; column-gap: 16px; row-gap: 3px; font-size: 12px; }
.rmt-flow-values > div { display: flex; align-items: baseline; gap: 5px; }
.rmt-flow a { color: var(--blue); font-weight: 650; }
.rmt-empty { color: var(--muted); font-size: 12px; }
.rmt-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px !important; overflow: hidden; clip-path: inset(50%); white-space: nowrap; border: 0; }
@media (max-width: 740px) {
  .rmt-stages { grid-template-columns: minmax(0, 1fr); }
  .rmt-period button, .rmt-triads button, .rmt-toolbar select { min-height: 36px; }
}
@media (max-width: 450px) {
  .rmt-toolbar label { width: 100%; }
  .rmt-toolbar select { flex: 1; min-width: 0; }
  .rmt-routes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rmt-routes button { min-height: 40px; }
}
</style>
"""

SCRIPT = """
<script>
(() => {
  const panel = document.getElementById("route-market-panel");
  const dataNode = document.getElementById("route-market-data");
  const groups = JSON.parse(dataNode.textContent).groups || [];
  const dom = (id) => panel.querySelector("#rmt-" + id);
  const labels = {
    US: {name: "美国", currency: "美元", equity: "标普500"},
    CN: {name: "中国", currency: "人民币", equity: "上证综指"},
    JP: {name: "日本", currency: "日元", equity: "日经225"},
    DE: {name: "德国（欧元代理）", currency: "欧元", equity: "DAX"},
    RU: {name: "俄罗斯", currency: "卢布", equity: "MOEX"}
  };
  const market = (code) => labels[code] || {name: code, currency: code, equity: "股指"};
  const statusLabel = {available: "已更新", pending: "待观察", unavailable: "暂无数据"};
  const flowStatusLabel = {published: "已发布", pending: "待发布", unavailable: "暂无数据"};
  const verdictBadge = {official: "官方净买入", price: "价格线索", waiting: "待确认"};
  const verdictFallback = {
    kind: "waiting",
    headline: "暂不能判断",
    explanation: "等待终点市场的债券和股指观察。"
  };
  const horizons = [["1", "后 1 日"], ["5", "后 5 日"]];
  const formatters = new Map();
  let groupId = groups[0]?.id || "JP";
  let period = "weekly";
  let observation = "";
  let routeId = "";
  let activeWindow = null;
  let earlierResult = null;

  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const number = (value, places) => {
    if (!finite(value)) return "—";
    if (!formatters.has(places)) {
      formatters.set(places, new Intl.NumberFormat("zh-CN", {maximumFractionDigits: places}));
    }
    return formatters.get(places).format(value);
  };
  const signed = (value, digits, unit = "") => {
    if (!finite(value)) return "—";
    const display = Number(value.toFixed(digits)) || 0;
    return (display > 0 ? "+" : "") + number(display, digits) + unit;
  };
  const markChange = (el, value, digits = 2) => {
    const display = finite(value) ? Number(value.toFixed(digits)) : 0;
    el.classList.toggle("rmt-value-up", display > 0);
    el.classList.toggle("rmt-value-down", display < 0);
  };
  const element = (tag, value = "") => {
    const el = document.createElement(tag);
    el.textContent = value;
    return el;
  };
  const setText = (id, value) => { dom(id).textContent = value; };
  const row = (heading, values, hint = "") => {
    const tr = element("tr");
    const th = element("th", heading);
    th.scope = "row";
    if (hint) th.append(element("small", hint));
    tr.append(th, ...values.map((value) => element("td", value)));
    return tr;
  };
  const pair = (label, value, change) => {
    const wrapper = element("div");
    const dd = element("dd", value);
    markChange(dd, change);
    wrapper.append(element("dt", label), dd);
    return wrapper;
  };
  const datePair = (base, end) => base && end ? `${base} 至 ${end}` : base || end || "";
  const pressed = (nodes, match) => {
    nodes.forEach((btn) => btn.setAttribute("aria-pressed", String(match(btn))));
  };
  const groupButtons = panel.querySelectorAll("[data-rmt-group]");
  const periodButtons = panel.querySelectorAll("[data-rmt-period]");
  const routeButtons = () => panel.querySelectorAll("[data-rmt-route]");
  const activeGroup = () => groups.find((item) => item.id === groupId);

  const renderFx = (selected) => {
    const from = market(selected.origin).currency;
    const to = market(selected.destination).currency;
    const rounded = finite(selected.score) ? Number(selected.score.toFixed(3)) : null;
    setText("fx-dates", datePair(activeWindow.base_date, activeWindow.signal_date));
    setText("fx-direction", rounded === null ? "暂无汇率分数" :
      rounded === 0 ? `${from}兑${to}基本持平` :
      `${from}兑${to}的合成汇率${rounded > 0 ? "上升" : "下降"}`);
    dom("fx-values").replaceChildren(
      pair("合成（对数百分点）", signed(selected.score, 3), selected.score),
      pair("同向直兑", signed(selected.direct, 3), selected.direct),
      pair("合成与直兑之差", signed(selected.residual, 3), selected.residual)
    );
  };

  const renderBond = (selected, destination) => {
    const bond = selected.bond || {};
    setText("bond-title", destination.name + " · 债券");
    setText("bond-dates", bond.date ? datePair(bond.base_date, bond.date) :
      bond.status === "pending" ? "等待下一次完整债券观察" : "当前日期暂无完整债券观察");
    dom("bond-rows").replaceChildren(...[
      ["short", "短端"], ["mid", "中端"], ["long", "长端"]
    ].map(([key, label]) => {
      const group = bond.groups?.[key] || {};
      const available = group.status === "available" && finite(group.yield);
      const yieldText = available ? `${number(group.yield, 3)}%` : "—";
      const change = available ? signed(group.change_bp, 2, " bp") :
        statusLabel[group.status || bond.status] || "暂无数据";
      const detail = (group.tenors || []).join("/") ||
        (selected.destination === "RU" && key === "short" ? "暂无短端序列" : "");
      const tr = row(label, [yieldText, change], detail);
      markChange(tr.lastElementChild, group.change_bp);
      return tr;
    }));
  };

  const renderEquity = (selected, destination) => {
    const equity = selected.equity || {};
    setText("equity-title", equity.label || destination.equity);
    setText("equity-base", equity.base_date ?
      `基准收盘 ${equity.base_date}${finite(equity.base_value) ? " · " + number(equity.base_value, 2) : ""}` :
      equity.status === "pending" ? "等待债券确认后的首个股指收盘" : "暂无可匹配的股指收盘");
    dom("equity-rows").replaceChildren(...horizons.map(([key, label]) => {
      const item = equity.horizons?.[key] || {};
      const available = item.status === "available" && finite(item.return_pct);
      const change = available ? signed(item.return_pct, 2, "%") :
        statusLabel[item.status || equity.status] || "暂无数据";
      const tr = row(label, [item.date || "—", change]);
      markChange(tr.lastElementChild, item.return_pct);
      if (finite(item.value)) tr.children[1].title = "收盘 " + number(item.value, 2);
      return tr;
    }));
  };

  const renderFlow = (selected, destination) => {
    const flow = selected.flow || {};
    setText("flow-title", "实际净买入 · " + destination.name);
    const state = flow.status || "unavailable";
    setText("flow-status", flowStatusLabel[state] || "暂无数据");
    dom("flow-status").dataset.state = state;
    const report = datePair(flow.week_start, flow.week_end);
    const publication = flow.publication_date ?
      `${state === "published" ? "发布日期" : "预计发布"} ${flow.publication_date}` : "";
    setText("flow-dates", [report ? "报告周 " + report : "", publication].filter(Boolean).join("  ·  "));
    const fields = [
      ["短期债", flow.short_net], ["中长期债", flow.long_net], ["股票及基金", flow.equity_net]
    ];
    dom("flow-values").replaceChildren(...(state === "published" ?
      fields.filter(([, value]) => finite(value)).map(([label, value]) => pair(
        label, signed(value, 2, flow.unit ? " " + flow.unit : ""), value
      )) : []));
    setText("flow-detail", flow.detail || (state === "unavailable" ? "暂无可对齐的公开净买入统计。" : ""));
    setSourceLink("flow-source", flow);
  };

  const setSourceLink = (id, flow) => {
    const link = dom(id);
    const url = flow.source_url;
    link.hidden = typeof url !== "string" || !url.startsWith("https://");
    link.removeAttribute("href");
    if (!link.hidden) {
      link.href = url;
      link.textContent = flow.source || "数据来源";
    }
  };

  const renderVerdict = (selected, destination) => {
    const verdict = selected.assessment || verdictFallback;
    const flow = selected.flow || {};
    dom("verdict").dataset.kind = verdict.kind;
    dom("verdict-badge").dataset.state = verdict.kind === "official" ? "published" :
      verdict.kind === "waiting" ? "pending" : "";
    setText("verdict-market", destination.name + "市场");
    setText("verdict-badge", verdictBadge[verdict.kind] || verdictBadge.waiting);
    setText("verdict-title", verdict.headline);
    setText("verdict-explanation", verdict.explanation);
    dom("verdict-values").replaceChildren(...(verdict.details || []).map(({label, value}) => pair(label, value)));

    const scheduled = flow.status === "pending" && flow.publication_date;
    const reference = verdict.kind === "official" ?
      (flow.publication_date ? "发布日期 " + flow.publication_date : "") :
      scheduled ? "官方数据预计 " + flow.publication_date + " 发布（日本时间）" : "";
    setText("verdict-date", reference);
    setSourceLink("verdict-source", verdict.kind === "official" || scheduled ? flow : {});
    dom("verdict-reference").hidden = !reference && dom("verdict-source").hidden;

    earlierResult = null;
    if (verdict.kind === "waiting") {
      for (const item of activeGroup()?.[period] || []) {
        if (item.signal_date >= activeWindow.signal_date) continue;
        const prior = item.routes.find((route) => route.id === routeId)?.assessment;
        if (prior?.kind === "official" || prior?.kind === "price") {
          earlierResult = item.signal_date;
          setText("history-preview", `${item.signal_date} · ${prior.headline}`);
          break;
        }
      }
    }
    dom("history-button").hidden = !earlierResult;
    setText("announcement", `${selected.label} · ${destination.name} · ${activeWindow.signal_date} · ${verdict.headline}`);
  };

  const renderDetails = () => {
    const selected = activeWindow?.routes?.find((route) => route.id === routeId);
    dom("empty").hidden = Boolean(selected);
    for (const id of ["verdict", "evidence", "stages", "flow"]) dom(id).hidden = !selected;
    pressed(routeButtons(), (btn) => btn.dataset.rmtRoute === routeId);
    if (!selected) {
      const route = activeGroup()?.routes?.find((item) => item.id === routeId);
      setText("announcement", route ? route.label + " · 所选周期暂无共同收盘数据" : "所选周期暂无共同收盘数据");
      return;
    }
    const destination = market(selected.destination);
    renderVerdict(selected, destination);
    renderFx(selected);
    renderBond(selected, destination);
    renderEquity(selected, destination);
    renderFlow(selected, destination);
  };
  const renderRoutes = () => {
    const routes = activeWindow?.routes || activeGroup()?.routes || [];
    if (!routes.some((route) => route.id === routeId)) {
      routeId = activeWindow?.best_route_id || (routes.find((route) => route.rank === 1) || routes[0])?.id || "";
    }
    const stableOrder = [...routes].sort((a, b) => a.id.localeCompare(b.id));
    dom("routes").replaceChildren(...stableOrder.map((route) => {
      const button = element("button", route.label);
      button.type = "button";
      button.dataset.rmtRoute = route.id;
      if (route.rank === 1 && route.score > 0) button.append(element("small", "最高分"));
      button.addEventListener("click", () => {
        routeId = route.id;
        renderDetails();
      });
      return button;
    }));
    renderDetails();
  };
  const renderWindows = () => {
    const list = activeGroup()?.[period] || [];
    const select = dom("window");
    activeWindow = list.find((item) => item.signal_date === observation) || list[0] || null;
    observation = activeWindow?.signal_date || "";
    select.replaceChildren(...list.map((item) => {
      const option = element("option", datePair(item.base_date, item.signal_date));
      option.value = item.signal_date;
      return option;
    }));
    select.disabled = !list.length;
    select.value = observation;
    pressed(groupButtons, (btn) => btn.dataset.rmtGroup === groupId);
    pressed(periodButtons, (btn) => btn.dataset.rmtPeriod === period);
    renderRoutes();
  };
  groupButtons.forEach((button) => button.addEventListener("click", () => {
    if (groupId === button.dataset.rmtGroup) return;
    groupId = button.dataset.rmtGroup;
    routeId = "";
    renderWindows();
  }));
  periodButtons.forEach((button) => button.addEventListener("click", () => {
    if (period === button.dataset.rmtPeriod) return;
    period = button.dataset.rmtPeriod;
    observation = "";
    renderWindows();
  }));
  dom("history-button").addEventListener("click", () => {
    if (!earlierResult) return;
    observation = earlierResult;
    renderWindows();
    dom("verdict-title").focus();
  });
  dom("window").addEventListener("change", (event) => {
    observation = event.currentTarget.value;
    renderWindows();
  });
  renderWindows();
})();
</script>
"""


def render_route_market_panel(payload: dict) -> str:
    """Build the tracker panel and safely embed its public data."""
    public_json = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    public_json = public_json.replace("<", "\\u003c")
    return STYLES + PANEL + f'<script type="application/json" id="route-market-data">{public_json}</script>' + SCRIPT
