const app = document.querySelector("#app");
const cardTemplate = document.querySelector("#card-template");
const langToggle = document.querySelector("#lang-toggle");
const LANGUAGE_KEY = "scifigurehub.gallery.lang";
const RESULT_PAGE_SIZE = 60;

const DEFAULT_FILTERS = {
  q: "",
  sort: "quality",
  minScore: "0",
  review: "all",
  rounds: "all",
  journal: "all",
  subject: "all",
  dataset: "all",
};

const SUBJECT_LABELS = {
  biology: { en: "Biology", zh: "生物类" },
  physics: { en: "Physics", zh: "物理类" },
  materials: { en: "Materials", zh: "材料类" },
  materials_chemistry: { en: "Materials + Chemistry", zh: "材料与化学类" },
  chemistry: { en: "Chemistry", zh: "化学类" },
  environment: { en: "Environment", zh: "环境类" },
  electronic_information: { en: "Electronic Information", zh: "电子信息类" },
};

const SUBTYPE_LABELS_ZH = {
  bar: "柱状图",
  box: "箱线图",
  bubble_plot: "气泡图",
  confusion_matrix: "混淆矩阵",
  density: "密度图",
  dose_response: "剂量响应图",
  dot_plot: "点图",
  forest_plot: "森林图",
  grouped_bar: "分组柱状图",
  heatmap: "热图",
  histogram: "直方图",
  line: "折线图",
  matrix_plot: "矩阵图",
  multi_line: "多折线图",
  network_plot: "网络图",
  other_data_display: "其他数据展示",
  pr_curve: "PR 曲线",
  roc_curve: "ROC 曲线",
  sankey_alluvial: "桑基/冲积图",
  scatter: "散点图",
  scatter_with_fit: "拟合散点图",
  stacked_bar: "堆叠柱状图",
  survival_curve: "生存曲线",
  table_like: "表格型图",
  time_series: "时间序列",
  umap_tsne_pca: "降维图",
  violin: "小提琴图",
  volcano_plot: "火山图",
};

const TEXT = {
  en: {
    brandTag: "Scientific Figure Gallery",
    navHome: "Home",
    navCatalog: "Catalog",
    navFeatured: "Featured charts",
    langToggle: "中文",
    langToggleAria: "Switch to Chinese",
    loadingEyebrow: "Loading catalog",
    loadingTitle: "Reading normalized panel evidence.",
    errorEyebrow: "Catalog unavailable",
    errorTitle: "The gallery shell loaded, but the data index did not.",
    fileHint: "This gallery reads JSON with fetch, so open it through a local static server from the gallery folder.",
    buildHint: "Run tools/build_catalog.py to generate site-data/catalog.json, then reload.",
    heroEyebrow: "Journal figure evidence",
    heroTitle: "Explore reproducible scientific figures by discipline.",
    heroText: "Switch between disciplines, inspect reviewed statistical figure reproductions, and trace each panel back to its journal, paper metadata, code, and assessment evidence.",
    openCatalog: "Explore catalog",
    explore: "Explore {label}",
    disciplineMode: "Discipline mode",
    allDisciplines: "All disciplines",
    journals: "Journals",
    modeIntro: "Choose a discipline to switch the gallery mode. Chart types, journals, and panels update within that subject.",
    toolSearchTitle: "Search",
    toolSearchText: "Find panels by DOI, caption, subtype, or review evidence.",
    toolCompareTitle: "Compare",
    toolCompareText: "Inspect target and reproduced outputs side by side.",
    toolReviewTitle: "Review",
    toolReviewText: "Open final assessments, Qwen scores, and source assets.",
    reviewedPanels: "Reviewed panels",
    chartSubtypes: "Chart subtypes",
    avgQuality: "Avg quality /10",
    reviewPassed: "Review passed",
    liveCatalog: "Live catalog",
    allChartTypes: "All chart types",
    categoryIntro: "{count} panels before filters. Use the controls to search by DOI, caption, reviewer assessment, source metadata, or panel id.",
    results: "Results",
    panelNotFound: "Panel not found",
    panelNotFoundTitle: "No matching gallery record exists for this route.",
    panelNotFoundText: "The catalog may have been regenerated or the panel id may be incomplete.",
    returnCatalog: "Return to catalog",
    noCaption: "No caption was exported for this panel.",
    noAssessment: "No final assessment was exported.",
    quality: "Quality",
    review: "Review",
    rounds: "Rounds",
    pass: "Pass",
    open: "Open",
    targetPanel: "Target panel",
    reproducedPanel: "Reproduced panel",
    reviewerEvidence: "Reviewer evidence",
    assessment: "Assessment",
    finalReview: "Final review",
    qwenQualityEvidence: "Qwen quality evidence",
    splitRationale: "Panel split rationale",
    noSplitRationale: "No split rationale was exported.",
    sourceAndAssets: "Source and assets",
    provenance: "Provenance",
    dataset: "Dataset",
    journal: "Journal",
    publication: "Publication",
    doi: "DOI",
    figure: "Figure",
    panel: "Panel",
    sourceSet: "Source set",
    doiLanding: "DOI landing page",
    sourceFigure: "Source figure",
    reproductionCode: "Reproduction code",
    targetPdf: "Target PDF",
    reproducedPdf: "Reproduced PDF",
    reviewNotes: "Review notes",
    reviewSummary: "Review summary",
    runLog: "Run log",
    qwenScoreJson: "Qwen score JSON",
    more: "More {label}",
    samePaper: "Same paper",
    related: "Related",
    similarPanels: "Similar panels",
    relatedText: "Same paper first, then same subtype by quality score.",
    searchCatalog: "Search catalog",
    searchPlaceholder: "Search panel id, DOI, captions, review text...",
    sortResults: "Sort results",
    relevance: "Relevance",
    qualityScore: "Quality score",
    reviewConfidence: "Review confidence",
    publicationDate: "Publication date",
    subtype: "Subtype",
    paperDoi: "Paper / DOI",
    minimumQuality: "Minimum quality",
    anyScore: "Any score",
    qualityAtLeast: "Quality >= {score}",
    qualityEqual: "Quality = {score}",
    reviewStatus: "Review status",
    allReviews: "All reviews",
    passedOnly: "Passed only",
    openOnly: "Open only",
    reviewRounds: "Review rounds",
    anyRounds: "Any rounds",
    oneRound: "1 round",
    roundsAtMost: "<= {count} rounds",
    allJournals: "All journals",
    all: "All",
    resultSummary: "{shown} {noun} shown from {total} matching this route.",
    resultSummaryPaged: "Showing {shown} of {matched} matching panels. {total} panels are available in this route before filters.",
    loadMore: "Load more panels",
    panelSingular: "panel",
    panelPlural: "panels",
    noMatches: "No matches",
    noMatchesTitle: "No panel matches the current filters.",
    noMatchesText: "Clear filters or broaden the search across all chart types.",
    noActiveFilters: "No active filters. Showing the selected catalog route.",
    clearFilters: "Clear filters",
    searchChip: "Search: {value}",
    sortChip: "Sort: {value}",
    scoreChip: "Score >= {value}",
    reviewChip: "Review: {value}",
    roundsChip: "Rounds <= {value}",
    noDate: "No date",
    featuredPanel: "Featured panel",
    complexity: "Complexity",
    refineComplexity: "Refine complexity",
    complexityReason: "Complexity assessment",
    contentSummary: "Content summary",
    complexityAssessmentJson: "Complexity JSON",
    noEvidenceText: "No evidence text exported.",
    qwenSummary: "Overall quality {overall}/10. Clarity {clarity}/10, data purity {purity}/10, code reproducibility {code}/10, aesthetic score {aesthetic}/10. Complete panel: {complete}. Foreign overlap: {overlap}. Axis labels: {labels}. Axis ticks: {ticks}.",
    yes: "yes",
    no: "no",
    unknown: "unknown",
    openFullSize: "Open full size",
  },
  zh: {
    brandTag: "学术期刊图表画廊",
    navHome: "首页",
    navCatalog: "目录",
    navFeatured: "精选图表",
    langToggle: "EN",
    langToggleAria: "切换到英文版本",
    loadingEyebrow: "正在加载目录",
    loadingTitle: "正在读取标准化图表证据。",
    errorEyebrow: "目录不可用",
    errorTitle: "页面外壳已加载，但数据索引读取失败。",
    fileHint: "这个画廊通过 fetch 读取 JSON，请在 gallery 目录下用本地静态服务打开。",
    buildHint: "请运行 tools/build_catalog.py 生成 site-data/catalog.json 后刷新。",
    heroEyebrow: "学术期刊图表证据",
    heroTitle: "按学科探索可复现的科学统计图。",
    heroText: "在生物、物理等学科模式之间切换，查看已审核的统计图复现，并追溯每个面板对应的期刊、论文元数据、代码和评估证据。",
    openCatalog: "探索目录",
    explore: "探索 {label}",
    disciplineMode: "学科模式",
    allDisciplines: "全部学科",
    journals: "期刊",
    modeIntro: "选择学科即可切换画廊模式；图表类型、期刊和面板都会限定在该学科内。",
    toolSearchTitle: "搜索",
    toolSearchText: "按 DOI、图注、类型或审核证据定位面板。",
    toolCompareTitle: "对比",
    toolCompareText: "并排检查原始面板与复现输出。",
    toolReviewTitle: "评审",
    toolReviewText: "打开最终评估、Qwen 分数和来源资产。",
    reviewedPanels: "已审核面板",
    chartSubtypes: "图表类型",
    avgQuality: "平均质量 /10",
    reviewPassed: "审核通过",
    liveCatalog: "实时目录",
    allChartTypes: "全部图表类型",
    categoryIntro: "筛选前共有 {count} 个面板。可按 DOI、图注、审核结论、来源元数据或面板 ID 搜索。",
    results: "结果",
    panelNotFound: "未找到面板",
    panelNotFoundTitle: "当前路由没有匹配的画廊记录。",
    panelNotFoundText: "目录可能已经重新生成，或面板 ID 不完整。",
    returnCatalog: "返回目录",
    noCaption: "该面板没有导出图注。",
    noAssessment: "该面板没有导出最终评估。",
    quality: "质量",
    review: "审核",
    rounds: "轮次",
    pass: "通过",
    open: "待处理",
    targetPanel: "原始面板",
    reproducedPanel: "复现面板",
    reviewerEvidence: "审核证据",
    assessment: "评估",
    finalReview: "最终审核",
    qwenQualityEvidence: "Qwen 质量证据",
    splitRationale: "面板切分依据",
    noSplitRationale: "没有导出面板切分依据。",
    sourceAndAssets: "来源与资产",
    provenance: "来源信息",
    dataset: "数据集",
    journal: "期刊",
    publication: "发表日期",
    doi: "DOI",
    figure: "图号",
    panel: "面板",
    sourceSet: "来源批次",
    doiLanding: "DOI 页面",
    sourceFigure: "来源图",
    reproductionCode: "复现代码",
    targetPdf: "原始 PDF",
    reproducedPdf: "复现 PDF",
    reviewNotes: "审核笔记",
    reviewSummary: "审核摘要",
    runLog: "运行日志",
    qwenScoreJson: "Qwen 评分 JSON",
    more: "更多 {label}",
    samePaper: "同一论文",
    related: "相关",
    similarPanels: "相似面板",
    relatedText: "优先展示同一论文，其次按同类型质量分排序。",
    searchCatalog: "搜索目录",
    searchPlaceholder: "搜索面板 ID、DOI、图注、审核文本...",
    sortResults: "结果排序",
    relevance: "相关性",
    qualityScore: "质量分",
    reviewConfidence: "审核置信度",
    publicationDate: "发表日期",
    subtype: "图表类型",
    paperDoi: "论文 / DOI",
    minimumQuality: "最低质量",
    anyScore: "任意分数",
    qualityAtLeast: "质量 >= {score}",
    qualityEqual: "质量 = {score}",
    reviewStatus: "审核状态",
    allReviews: "全部审核",
    passedOnly: "仅通过",
    openOnly: "仅待处理",
    reviewRounds: "审核轮次",
    anyRounds: "任意轮次",
    oneRound: "1 轮",
    roundsAtMost: "<= {count} 轮",
    allJournals: "全部期刊",
    all: "全部",
    resultSummary: "当前显示 {shown} 个面板，共 {total} 个符合当前路由。",
    resultSummaryPaged: "当前显示 {shown} / {matched} 个筛选结果；当前路由筛选前共有 {total} 个面板。",
    loadMore: "加载更多面板",
    panelSingular: "面板",
    panelPlural: "面板",
    noMatches: "无匹配",
    noMatchesTitle: "当前筛选条件下没有匹配面板。",
    noMatchesText: "请清空筛选，或扩大到全部图表类型。",
    noActiveFilters: "当前没有启用筛选，正在显示所选目录路由。",
    clearFilters: "清空筛选",
    searchChip: "搜索：{value}",
    sortChip: "排序：{value}",
    scoreChip: "分数 >= {value}",
    reviewChip: "审核：{value}",
    roundsChip: "轮次 <= {value}",
    noDate: "无日期",
    featuredPanel: "精选面板",
    complexity: "复杂度",
    refineComplexity: "精修复杂度",
    complexityReason: "复杂度评估",
    contentSummary: "内容摘要",
    complexityAssessmentJson: "复杂度 JSON",
    noEvidenceText: "没有导出证据文本。",
    qwenSummary: "总体质量 {overall}/10。清晰度 {clarity}/10，数据纯度 {purity}/10，代码可复现性 {code}/10，美观度 {aesthetic}/10。完整面板：{complete}。外部重叠：{overlap}。坐标轴标签：{labels}。刻度：{ticks}。",
    yes: "是",
    no: "否",
    unknown: "未知",
    openFullSize: "打开原图",
  },
};

const state = {
  catalog: null,
  route: null,
  filters: { ...DEFAULT_FILTERS },
  lang: initialLanguage(),
  visibleCount: RESULT_PAGE_SIZE,
};

init();

async function init() {
  app.addEventListener("click", handleAppClick);
  if (langToggle) {
    langToggle.addEventListener("click", () => setLanguage(state.lang === "en" ? "zh" : "en"));
  }
  window.addEventListener("hashchange", renderRoute);
  updateChromeText();

  try {
    const response = await fetch("site-data/catalog.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Catalog request failed with ${response.status}`);
    }
    state.catalog = await response.json();
    renderRoute();
  } catch (error) {
    renderLoadError(error);
  }
}

function initialLanguage() {
  const pageLang = new URLSearchParams(window.location.search).get("lang");
  const hashLang = new URLSearchParams((window.location.hash.split("?")[1] || "")).get("lang");
  const requested = pageLang || hashLang;
  if (requested === "en" || requested === "zh") {
    return requested;
  }
  const stored = localStorage.getItem(LANGUAGE_KEY);
  if (stored === "en" || stored === "zh") {
    return stored;
  }
  return "en";
}

function setLanguage(lang) {
  state.lang = lang === "zh" ? "zh" : "en";
  localStorage.setItem(LANGUAGE_KEY, state.lang);
  const url = new URL(window.location.href);
  url.searchParams.set("lang", state.lang);
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  updateChromeText();
  renderRoute();
}

function updateChromeText() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.body.dataset.lang = state.lang;
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  if (langToggle) {
    langToggle.textContent = t("langToggle");
    langToggle.setAttribute("aria-label", t("langToggleAria"));
  }
}

function t(key, values = {}) {
  const value = (TEXT[state.lang] && TEXT[state.lang][key]) || TEXT.en[key] || key;
  return value.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? ""));
}

function renderLoadError(error) {
  const fileHint = window.location.protocol === "file:"
    ? t("fileHint")
    : t("buildHint");
  app.innerHTML = `
    <section class="empty-state">
      <p class="eyebrow">${escapeHtml(t("errorEyebrow"))}</p>
      <h1>${escapeHtml(t("errorTitle"))}</h1>
      <p>${escapeHtml(fileHint)}</p>
      <p class="muted-code">${escapeHtml(error.message)}</p>
    </section>
  `;
}

function renderRoute() {
  if (!state.catalog) {
    return;
  }

  const route = parseRoute();
  state.route = route;
  state.filters = route.filters;
  state.visibleCount = RESULT_PAGE_SIZE;
  document.body.dataset.view = route.type;

  if (route.type === "panel") {
    renderPanel(route);
    return;
  }

  if (route.type === "category") {
    renderCategory(route);
    return;
  }

  renderHome(route);
}

function parseRoute() {
  const raw = window.location.hash || "#/";
  const clean = raw.replace(/^#\/?/, "");
  const [pathPart = "", queryPart = ""] = clean.split("?");
  const segments = pathPart.split("/").filter(Boolean).map(decodeURIComponent);
  const params = new URLSearchParams(queryPart);
  const q = params.get("q") || "";
  const filters = {
    q,
    sort: params.get("sort") || (q ? "relevance" : DEFAULT_FILTERS.sort),
    minScore: params.get("minScore") || DEFAULT_FILTERS.minScore,
    review: params.get("review") || DEFAULT_FILTERS.review,
    rounds: params.get("rounds") || DEFAULT_FILTERS.rounds,
    journal: params.get("journal") || DEFAULT_FILTERS.journal,
    subject: params.get("subject") || DEFAULT_FILTERS.subject,
    dataset: params.get("dataset") || DEFAULT_FILTERS.dataset,
  };

  if (segments[0] === "panel") {
    if (segments.length >= 5) {
      return {
        type: "panel",
        datasetId: `${segments[1]}/${segments[2]}`,
        subtype: segments[3],
        panelId: segments.slice(4).join("/"),
        filters,
      };
    }
    return {
      type: "panel",
      datasetId: filters.dataset !== "all" ? filters.dataset : null,
      subtype: null,
      panelId: segments.slice(1).join("/"),
      filters,
    };
  }

  if (segments[0] === "category") {
    if (!segments[1] || segments[1] === "all") {
      return {
        type: "category",
        datasetId: filters.dataset !== "all" ? filters.dataset : null,
        subtype: "all",
        filters,
      };
    }
    if (segments.length >= 4) {
      return {
        type: "category",
        datasetId: `${segments[1]}/${segments[2]}`,
        subtype: segments[3],
        filters,
      };
    }
    return {
      type: "category",
      datasetId: filters.dataset !== "all" ? filters.dataset : null,
      subtype: segments[1],
      filters,
    };
  }

  return {
    type: "home",
    datasetId: filters.dataset !== "all" ? filters.dataset : null,
    subtype: "all",
    filters,
  };
}

function renderHome(route) {
  const stats = statsForRoute(route);
  const featuredPanels = topComplexityPanels(2, route);
  const topSubtype = subtypesForMode(route).slice().sort((a, b) => b.count - a.count)[0];
  document.title = "SciFigureHub Gallery";
  const topSubtypeLabel = formatSubtype(topSubtype ? topSubtype.name : "all");
  const activeDataset = activeDatasetId(route);

  app.innerHTML = `
    <section class="hero">
      <article class="hero-copy">
        <p class="eyebrow">${escapeHtml(t("heroEyebrow"))}</p>
        <h1>${escapeHtml(t("heroTitle"))}</h1>
        <p>${escapeHtml(t("heroText"))}</p>
        <div class="hero-actions">
          <a class="hero-action" href="${categoryHash(activeDataset, "all", route.filters)}">${escapeHtml(t("openCatalog"))}</a>
          <a class="ghost-link" href="${categoryHash(activeDataset, topSubtype ? topSubtype.name : "all", route.filters)}">${escapeHtml(t("explore", { label: topSubtypeLabel }))}</a>
        </div>
        ${renderToolCloud()}
      </article>
      <aside class="hero-board">
        <div class="ticker" aria-label="Catalog stats">
          ${metricBlock(stats.panelCount, t("reviewedPanels"))}
          ${metricBlock(stats.subtypeCount, t("chartSubtypes"))}
          ${metricBlock((stats.journals || []).length, t("journals"))}
          ${metricBlock(stats.averageQuality.toFixed(2), t("avgQuality"))}
        </div>
        <div class="market-stack">
          ${featuredPanels.map((item) => renderMarketTile(item)).join("")}
        </div>
      </aside>
    </section>

    ${renderSubjectSwitch(route)}
    ${renderControls(route, route.filters)}
    ${renderSubtypeRail(route)}

    <section class="section-head">
      <div>
        <p class="eyebrow">${escapeHtml(t("liveCatalog"))}</p>
        <h2>${escapeHtml(t("reviewedPanels"))}</h2>
      </div>
      <p class="js-result-summary"></p>
    </section>
    <div class="active-filters js-active-filters"></div>
    <section class="gallery-grid js-grid" aria-live="polite"></section>
  `;

  attachControls(route);
  renderResultSet(route, route.filters);
}

function renderCategory(route) {
  const subtypeLabel = route.subtype === "all" ? t("allChartTypes") : formatSubtype(route.subtype);
  const dataset = findDataset(route.datasetId);
  const items = baseItemsForRoute(route);
  document.title = `${subtypeLabel} - SciFigureHub Gallery`;

  app.innerHTML = `
    <section class="section-head category-head">
      <div>
        <nav class="breadcrumb" aria-label="Breadcrumb">
          <a href="#/">${escapeHtml(t("navHome"))}</a>
          <span>/</span>
          <a href="${categoryHash(activeDatasetId(route), "all", route.filters)}">${escapeHtml(t("navCatalog"))}</a>
          ${route.subtype !== "all" ? `<span>/</span><span>${escapeHtml(subtypeLabel)}</span>` : ""}
        </nav>
        <p class="eyebrow">${escapeHtml(modeLabel(route))}</p>
        <h1>${escapeHtml(subtypeLabel)}</h1>
      </div>
      <p>${escapeHtml(t("categoryIntro", { count: items.length }))}</p>
    </section>

    ${renderSubjectSwitch(route)}
    ${renderControls(route, route.filters)}
    ${renderSubtypeRail(route)}

    <section class="section-head">
      <div>
        <p class="eyebrow">${escapeHtml(t("results"))}</p>
        <h2>${escapeHtml(subtypeLabel)}</h2>
      </div>
      <p class="js-result-summary"></p>
    </section>
    <div class="active-filters js-active-filters"></div>
    <section class="gallery-grid js-grid" aria-live="polite"></section>
  `;

  attachControls(route);
  renderResultSet(route, route.filters);
}

function renderPanel(route) {
  const item = findPanel(route);
  if (!item) {
    document.title = "Panel not found - SciFigureHub Gallery";
    app.innerHTML = `
      <section class="empty-state">
        <p class="eyebrow">${escapeHtml(t("panelNotFound"))}</p>
        <h1>${escapeHtml(t("panelNotFoundTitle"))}</h1>
        <p>${escapeHtml(t("panelNotFoundText"))}</p>
        <a class="hero-action" href="#/category/all">${escapeHtml(t("returnCatalog"))}</a>
      </section>
    `;
    return;
  }

  document.title = `${paperTitle(item)} - SciFigureHub Gallery`;
  const subtypeLabel = formatSubtype(item.subtype);
  const caption = item.caption || t("noCaption");
  const assessment = item.review.finalAssessment || item.galleryRecord.finalAssessment || t("noAssessment");
  app.innerHTML = `
    <section class="detail-hero">
      <article class="detail-panel">
        <nav class="breadcrumb" aria-label="Breadcrumb">
          <a href="#/">${escapeHtml(t("navHome"))}</a>
          <span>/</span>
          <a href="#/category/all">${escapeHtml(t("navCatalog"))}</a>
          <span>/</span>
          <a href="${categoryHash(item.dataset.id, item.subtype, state.filters)}">${escapeHtml(subtypeLabel)}</a>
        </nav>
        <p class="eyebrow">${escapeHtml(subtypeLabel)}</p>
        <h1>${escapeHtml(paperTitle(item))}</h1>
        <p class="panel-id">${escapeHtml([item.title, item.id].filter(Boolean).join(" · "))}</p>
        <p>${escapeHtml(truncate(caption, 520))}</p>
        <div class="metrics-grid">
          ${metricCard(formatScore(item.qwen.overallQualityScore), t("quality"))}
          ${metricCard(item.review.passed ? t("pass") : t("open"), t("review"))}
          ${metricCard(`${formatNumber(item.review.roundsCompleted)}/${formatNumber(item.review.maxRounds || 4)}`, t("rounds"))}
          ${refineComplexityScore(item) !== null ? metricCard(`${formatScore(refineComplexityScore(item))}/10`, t("refineComplexity")) : ""}
        </div>
      </article>
      <div class="detail-images" aria-label="Target and reproduced figures">
        ${figureFrame(t("targetPanel"), item.paths.targetPreview || item.paths.target, item.paths.target, `${t("targetPanel")} ${item.id}`)}
        ${figureFrame(t("reproducedPanel"), item.paths.reproducePreview || item.paths.reproduce, item.paths.reproduce, `${t("reproducedPanel")} ${item.id}`)}
      </div>
    </section>

    <section class="detail-layout">
      <article class="detail-panel">
        <p class="eyebrow">${escapeHtml(t("reviewerEvidence"))}</p>
        <h2>${escapeHtml(t("assessment"))}</h2>
        <div class="evidence-list">
          ${evidenceCard(t("finalReview"), assessment)}
          ${evidenceCard(t("qwenQualityEvidence"), qwenSummary(item))}
          ${item.refineComplexity && item.refineComplexity.reason ? evidenceCard(t("complexityReason"), item.refineComplexity.reason) : ""}
          ${item.refineComplexity && item.refineComplexity.captionSummary ? evidenceCard(t("contentSummary"), item.refineComplexity.captionSummary) : ""}
          ${evidenceCard(t("splitRationale"), item.splitReason || t("noSplitRationale"))}
        </div>
      </article>
      <aside class="detail-panel">
        <p class="eyebrow">${escapeHtml(t("sourceAndAssets"))}</p>
        <h2>${escapeHtml(t("provenance"))}</h2>
        <dl class="meta-list">
          ${metaRow(t("dataset"), item.dataset.title)}
          ${metaRow(t("journal"), item.journal)}
          ${metaRow(t("publication"), item.publicationDate)}
          ${metaRow(t("doi"), item.doi)}
          ${metaRow(t("figure"), item.figureLabel)}
          ${metaRow(t("panel"), item.panelLabel)}
          ${metaRow(t("sourceSet"), item.galleryRecord.sourceSet)}
        </dl>
        <div class="data-links">
          ${assetLink(t("doiLanding"), item.doiUrl)}
          ${assetLink(t("sourceFigure"), item.sourceFigureUrl)}
          ${assetLink(t("reproductionCode"), item.paths.reproduceCode)}
          ${assetLink(t("targetPdf"), item.paths.targetPdf)}
          ${assetLink(t("reproducedPdf"), item.paths.reproducePdf)}
          ${assetLink(t("reviewNotes"), item.paths.reviewNotes)}
          ${assetLink(t("reviewSummary"), item.paths.reviewSummary)}
          ${assetLink(t("runLog"), item.paths.runLog)}
          ${assetLink(t("qwenScoreJson"), item.paths.qwenScore)}
          ${assetLink(t("complexityAssessmentJson"), item.paths.refineComplexityAssessment)}
        </div>
        <div class="detail-actions">
          <a class="ghost-link" href="${categoryHash(item.dataset.id, item.subtype, state.filters)}">${escapeHtml(t("more", { label: subtypeLabel }))}</a>
          ${item.doi ? `<a class="ghost-link" href="${categoryHash(item.dataset.id, "all", { ...state.filters, q: item.doi, sort: "relevance" })}">${escapeHtml(t("samePaper"))}</a>` : ""}
        </div>
      </aside>
    </section>

    <section class="section-head">
      <div>
        <p class="eyebrow">${escapeHtml(t("related"))}</p>
        <h2>${escapeHtml(t("similarPanels"))}</h2>
      </div>
      <p>${escapeHtml(t("relatedText"))}</p>
    </section>
    <section class="gallery-grid js-related-grid"></section>
  `;

  renderRelated(item);
}

function renderSubjectSwitch(route) {
  const subjects = subjectSummaries();
  const activeSubject = activeSubjectId(route);
  const activeDataset = activeDatasetId(route);
  const activeSubtype = route.type === "category" ? route.subtype : "all";
  const allClass = activeSubject === "all" && !activeDataset ? "subject-pill is-active" : "subject-pill";
  const allHref = categoryHash(null, activeSubtype, { ...state.filters, subject: "all", dataset: "all" });
  return `
    <section class="mode-panel" aria-label="${attr(t("disciplineMode"))}">
      <div class="mode-copy">
        <p class="eyebrow">${escapeHtml(t("disciplineMode"))}</p>
        <p>${escapeHtml(t("modeIntro"))}</p>
      </div>
      <nav class="subject-switch">
        <a class="${allClass}" href="${allHref}">
          <strong>${escapeHtml(t("allDisciplines"))}</strong>
          <span>${escapeHtml(state.catalog.stats.panelCount)} ${escapeHtml(t("panelPlural"))}</span>
        </a>
        ${subjects.map((subject) => {
          const klass = subject.id === activeSubject ? "subject-pill is-active" : "subject-pill";
          const href = categoryHash(null, activeSubtype, { ...state.filters, subject: subject.id, dataset: "all" });
          return `
            <a class="${klass}" href="${href}">
              <strong>${escapeHtml(subjectLabel(subject.id))}</strong>
              <span>${escapeHtml(subject.panelCount)} ${escapeHtml(t("panelPlural"))} · ${escapeHtml(subject.journalCount)} ${escapeHtml(t("journals"))}</span>
            </a>
          `;
        }).join("")}
      </nav>
    </section>
  `;
}

function renderControls(route, filters) {
  const journals = journalsForRoute(route);
  return `
    <section class="control-panel" data-controls>
      <label class="search-box">
        <span class="visually-hidden">${escapeHtml(t("searchCatalog"))}</span>
        <input type="search" data-filter="q" value="${attr(filters.q)}" placeholder="${attr(t("searchPlaceholder"))}">
      </label>
      <label class="select-box">
        <span class="visually-hidden">${escapeHtml(t("sortResults"))}</span>
        <select data-filter="sort">
          ${option("relevance", t("relevance"), filters.sort)}
          ${option("quality", t("qualityScore"), filters.sort)}
          ${option("complexity", t("complexity"), filters.sort)}
          ${option("review", t("reviewConfidence"), filters.sort)}
          ${option("date", t("publicationDate"), filters.sort)}
          ${option("subtype", t("subtype"), filters.sort)}
          ${option("paper", t("paperDoi"), filters.sort)}
        </select>
      </label>
      <label class="select-box">
        <span class="visually-hidden">${escapeHtml(t("minimumQuality"))}</span>
        <select data-filter="minScore">
          ${option("0", t("anyScore"), filters.minScore)}
          ${option("8", t("qualityAtLeast", { score: 8 }), filters.minScore)}
          ${option("9", t("qualityAtLeast", { score: 9 }), filters.minScore)}
          ${option("9.5", t("qualityAtLeast", { score: 9.5 }), filters.minScore)}
          ${option("10", t("qualityEqual", { score: 10 }), filters.minScore)}
        </select>
      </label>
      <label class="select-box">
        <span class="visually-hidden">${escapeHtml(t("reviewStatus"))}</span>
        <select data-filter="review">
          ${option("all", t("allReviews"), filters.review)}
          ${option("passed", t("passedOnly"), filters.review)}
          ${option("open", t("openOnly"), filters.review)}
        </select>
      </label>
      <label class="select-box">
        <span class="visually-hidden">${escapeHtml(t("reviewRounds"))}</span>
        <select data-filter="rounds">
          ${option("all", t("anyRounds"), filters.rounds)}
          ${option("1", t("oneRound"), filters.rounds)}
          ${option("2", t("roundsAtMost", { count: 2 }), filters.rounds)}
          ${option("3", t("roundsAtMost", { count: 3 }), filters.rounds)}
          ${option("4", t("roundsAtMost", { count: 4 }), filters.rounds)}
        </select>
      </label>
      <label class="select-box">
        <span class="visually-hidden">${escapeHtml(t("journal"))}</span>
        <select data-filter="journal">
          ${option("all", t("allJournals"), filters.journal)}
          ${journals.map((journal) => option(journal.name, `${journal.name} (${journal.count})`, filters.journal)).join("")}
        </select>
      </label>
    </section>
  `;
}

function renderSubtypeRail(route) {
  const active = route.type === "category" ? route.subtype : "all";
  const datasetId = activeDatasetId(route);
  const subtypes = subtypesForMode(route);
  const modeCount = modeItemsForRoute(route).length;
  const allClass = active === "all" ? "pill is-active" : "pill";
  return `
    <nav class="subtype-rail" aria-label="Chart subtype navigation">
      <a class="${allClass}" href="${categoryHash(datasetId, "all", state.filters)}">${escapeHtml(t("all"))} ${modeCount}</a>
      ${subtypes.map((subtype) => {
        const klass = subtype.name === active ? "pill is-active" : "pill";
        return `<a class="${klass}" href="${categoryHash(datasetId, subtype.name, state.filters)}">${escapeHtml(formatSubtype(subtype.name))} ${subtype.count}</a>`;
      }).join("")}
    </nav>
  `;
}

function renderResultSet(route, filters) {
  const grid = document.querySelector(".js-grid");
  const summary = document.querySelector(".js-result-summary");
  const active = document.querySelector(".js-active-filters");
  if (!grid || !summary || !active) {
    return;
  }

  const baseItems = baseItemsForRoute(route);
  const filtered = filterItems(baseItems, filters);
  const sorted = sortItems(filtered, filters);
  const noun = sorted.length === 1 ? t("panelSingular") : t("panelPlural");
  const shown = Math.min(state.visibleCount, sorted.length);
  const visible = sorted.slice(0, shown);

  summary.textContent = t("resultSummaryPaged", { shown, matched: sorted.length, noun, total: baseItems.length });
  active.innerHTML = renderActiveFilters(filters);
  grid.replaceChildren(...visible.map((item) => createCard(item, route, filters)));

  if (!sorted.length) {
    grid.innerHTML = `
      <article class="empty-state grid-empty">
        <p class="eyebrow">${escapeHtml(t("noMatches"))}</p>
        <h1>${escapeHtml(t("noMatchesTitle"))}</h1>
        <p>${escapeHtml(t("noMatchesText"))}</p>
      </article>
    `;
  } else if (shown < sorted.length) {
    grid.appendChild(createLoadMoreCard(sorted.length - shown));
  }
}

function createLoadMoreCard(remaining) {
  const card = document.createElement("article");
  card.className = "load-more-card";
  card.innerHTML = `
    <button class="ghost-link" type="button" data-load-more>
      ${escapeHtml(t("loadMore"))}
    </button>
    <span>${escapeHtml(remaining)} ${escapeHtml(t("panelPlural"))}</span>
  `;
  return card;
}

function attachControls(route) {
  const controls = document.querySelector("[data-controls]");
  if (!controls) {
    return;
  }
  controls.querySelectorAll("[data-filter]").forEach((control) => {
    const key = control.dataset.filter;
    if (key === "q") {
      control.addEventListener("input", () => {
        const next = { ...state.filters, q: control.value };
        if (next.q && !new URLSearchParams((window.location.hash.split("?")[1] || "")).has("sort")) {
          next.sort = "relevance";
        }
        applyFilters(route, next);
      });
      return;
    }
    control.addEventListener("change", () => {
      applyFilters(route, { ...state.filters, [key]: control.value });
    });
  });
}

function applyFilters(route, nextFilters) {
  state.filters = normalizeFilters(nextFilters);
  state.route = { ...route, filters: state.filters };
  state.visibleCount = RESULT_PAGE_SIZE;
  const nextHash = routeHash(state.route, state.filters);
  window.history.replaceState(null, "", nextHash);
  syncControls(state.filters);
  refreshSubtypeRail(state.route);
  renderResultSet(state.route, state.filters);
}

function refreshSubtypeRail(route) {
  const rail = document.querySelector(".subtype-rail");
  if (rail) {
    rail.outerHTML = renderSubtypeRail(route);
  }
}

function syncControls(filters) {
  document.querySelectorAll("[data-filter]").forEach((control) => {
    const key = control.dataset.filter;
    if (Object.prototype.hasOwnProperty.call(filters, key) && control.value !== filters[key]) {
      control.value = filters[key];
    }
  });
}

function handleAppClick(event) {
  const loadMore = event.target.closest("[data-load-more]");
  if (loadMore) {
    event.preventDefault();
    state.visibleCount += RESULT_PAGE_SIZE;
    renderResultSet(state.route, state.filters);
    return;
  }

  const clear = event.target.closest("[data-clear-filters]");
  if (clear) {
    event.preventDefault();
    applyFilters(state.route, { ...DEFAULT_FILTERS });
    return;
  }

  const remove = event.target.closest("[data-remove-filter]");
  if (remove) {
    event.preventDefault();
    const key = remove.dataset.removeFilter;
    const next = { ...state.filters, [key]: DEFAULT_FILTERS[key] };
    if (key === "q" && next.sort === "relevance") {
      next.sort = DEFAULT_FILTERS.sort;
    }
    applyFilters(state.route, next);
  }
}

function baseItemsForRoute(route) {
  let items = state.catalog.items || [];
  const routeDataset = route.datasetId || (route.filters.dataset !== "all" ? route.filters.dataset : null);
  if (routeDataset) {
    items = items.filter((item) => item.dataset.id === routeDataset);
  }
  if (!routeDataset && route.filters.subject !== "all") {
    items = items.filter((item) => item.dataset.subject === route.filters.subject);
  }
  if (route.type === "category" && route.subtype && route.subtype !== "all") {
    items = items.filter((item) => item.subtype === route.subtype);
  }
  return items;
}

function filterItems(items, filters) {
  const query = filters.q.trim().toLowerCase();
  const minScore = Number(filters.minScore || 0);
  return items.filter((item) => {
    if (query && !itemSearchText(item).includes(query)) {
      return false;
    }
    if (Number(item.qwen.overallQualityScore || 0) < minScore) {
      return false;
    }
    if (filters.review === "passed" && !item.review.passed) {
      return false;
    }
    if (filters.review === "open" && item.review.passed) {
      return false;
    }
    if (filters.rounds !== "all" && Number(item.review.roundsCompleted || 0) > Number(filters.rounds)) {
      return false;
    }
    if (filters.journal !== "all" && item.journal !== filters.journal) {
      return false;
    }
    if (filters.subject !== "all" && item.dataset.subject !== filters.subject) {
      return false;
    }
    if (filters.dataset !== "all" && item.dataset.id !== filters.dataset) {
      return false;
    }
    return true;
  });
}

function sortItems(items, filters) {
  const copy = [...items];
  if (filters.sort === "relevance" && filters.q.trim()) {
    return copy.sort((a, b) => relevanceScore(b, filters.q) - relevanceScore(a, filters.q) || b.sort.quality - a.sort.quality);
  }
  if (filters.sort === "review") {
    return copy.sort((a, b) => b.sort.review - a.sort.review || b.sort.quality - a.sort.quality);
  }
  if (filters.sort === "complexity") {
    return copy.sort((a, b) => panelComplexitySortValue(b) - panelComplexitySortValue(a) || b.sort.quality - a.sort.quality);
  }
  if (filters.sort === "date") {
    return copy.sort((a, b) => (b.publicationDate || "").localeCompare(a.publicationDate || "") || b.sort.quality - a.sort.quality);
  }
  if (filters.sort === "subtype") {
    return copy.sort((a, b) => a.subtype.localeCompare(b.subtype) || b.sort.quality - a.sort.quality);
  }
  if (filters.sort === "paper") {
    return copy.sort((a, b) => (a.doi || "").localeCompare(b.doi || "") || a.id.localeCompare(b.id));
  }
  return copy.sort((a, b) => b.sort.quality - a.sort.quality || b.sort.review - a.sort.review);
}

function itemSearchText(item) {
  if (item._searchText) {
    return item._searchText;
  }
  item._searchText = [
    item.dataset && item.dataset.title,
    item.id,
    item.subtype,
    item.doi,
    item.journal,
    item.figureLabel,
    item.panelLabel,
    item.caption,
    item.figureCaption,
    item.qwen && item.qwen.shortReason,
    item.review && item.review.finalAssessment,
    item.refineComplexity && item.refineComplexity.reason,
    item.refineComplexity && item.refineComplexity.captionSummary,
  ].filter(Boolean).join(" ").toLowerCase();
  return item._searchText;
}

function relevanceScore(item, query) {
  const q = query.trim().toLowerCase();
  if (!q) {
    return 0;
  }
  let score = 0;
  if (item.id.toLowerCase().includes(q)) score += 10;
  if ((item.doi || "").toLowerCase().includes(q)) score += 8;
  if (item.subtype.toLowerCase().includes(q)) score += 6;
  if ((item.caption || "").toLowerCase().includes(q)) score += 4;
  if ((item.review.finalAssessment || "").toLowerCase().includes(q)) score += 3;
  if ((item.qwen.shortReason || "").toLowerCase().includes(q)) score += 2;
  return score;
}

function createCard(item, route, filters) {
  const fragment = cardTemplate.content.cloneNode(true);
  const detailLink = panelHash(item, filters);
  const target = fragment.querySelector("[data-field='target']");
  const reproduce = fragment.querySelector("[data-field='reproduce']");
  setLink(fragment, "detailLink", detailLink);
  setLink(fragment, "titleLink", detailLink);
  setLink(fragment, "subtypeLink", categoryHash(item.dataset.id, item.subtype, state.filters));
  target.src = item.paths.targetPreview || item.paths.target;
  target.alt = `${t("targetPanel")} ${item.id}`;
  target.decoding = "async";
  reproduce.src = item.paths.reproducePreview || item.paths.reproduce;
  reproduce.alt = `${t("reproducedPanel")} ${item.id}`;
  reproduce.decoding = "async";
  fragment.querySelector("[data-field='subtypeLink']").textContent = formatSubtype(item.subtype);
  fragment.querySelector("[data-field='date']").textContent = [item.journal, item.publicationDate].filter(Boolean).join(" · ") || t("noDate");
  fragment.querySelector("[data-field='titleLink']").textContent = paperTitle(item);
  fragment.querySelector("[data-field='caption']").textContent = truncate(item.caption || item.review.finalAssessment || "", 240);
  fragment.querySelector("[data-field='quality']").textContent = formatScore(item.qwen.overallQualityScore);
  fragment.querySelector("[data-field='complexity']").textContent = formatComplexityMetric(item);
  fragment.querySelector("[data-field='review']").textContent = item.review.passed ? t("pass") : t("open");
  fragment.querySelector("[data-field='rounds']").textContent = `${formatNumber(item.review.roundsCompleted)}/${formatNumber(item.review.maxRounds || 4)}`;
  fragment.querySelector("[data-field='qualityLabel']").textContent = t("quality");
  fragment.querySelector("[data-field='complexityLabel']").textContent = t("complexity");
  fragment.querySelector("[data-field='reviewLabel']").textContent = t("review");
  fragment.querySelector("[data-field='roundsLabel']").textContent = t("rounds");
  return fragment;
}

function renderRelated(item) {
  const grid = document.querySelector(".js-related-grid");
  if (!grid) {
    return;
  }
  const related = state.catalog.items
    .filter((candidate) => candidate.uid !== item.uid && (candidate.doi === item.doi || candidate.subtype === item.subtype))
    .sort((a, b) => {
      const paperA = a.doi === item.doi ? 1 : 0;
      const paperB = b.doi === item.doi ? 1 : 0;
      return paperB - paperA || b.sort.quality - a.sort.quality;
    })
    .slice(0, 6);
  grid.replaceChildren(...related.map((candidate) => createCard(candidate, state.route, state.filters)));
}

function renderActiveFilters(filters) {
  const chips = [];
  if (filters.q) chips.push(filterChip("q", t("searchChip", { value: filters.q })));
  if (filters.sort !== DEFAULT_FILTERS.sort && !(filters.q && filters.sort === "relevance")) chips.push(filterChip("sort", t("sortChip", { value: labelForSort(filters.sort) })));
  if (filters.minScore !== DEFAULT_FILTERS.minScore) chips.push(filterChip("minScore", t("scoreChip", { value: filters.minScore })));
  if (filters.review !== DEFAULT_FILTERS.review) chips.push(filterChip("review", t("reviewChip", { value: labelForReview(filters.review) })));
  if (filters.rounds !== DEFAULT_FILTERS.rounds) chips.push(filterChip("rounds", t("roundsChip", { value: filters.rounds })));
  if (filters.journal !== DEFAULT_FILTERS.journal) chips.push(filterChip("journal", filters.journal));
  if (filters.subject !== DEFAULT_FILTERS.subject) chips.push(filterChip("subject", subjectLabel(filters.subject)));
  if (filters.dataset !== DEFAULT_FILTERS.dataset) chips.push(filterChip("dataset", filters.dataset));

  if (!chips.length) {
    return `<span class="filter-note">${escapeHtml(t("noActiveFilters"))}</span>`;
  }
  return `${chips.join("")}<button class="clear-button" type="button" data-clear-filters>${escapeHtml(t("clearFilters"))}</button>`;
}

function filterChip(key, label) {
  return `<button class="filter-chip" type="button" data-remove-filter="${attr(key)}">${escapeHtml(label)} <span aria-hidden="true">x</span></button>`;
}

function routeHash(route, filters = {}) {
  if (!route) {
    return "#/";
  }
  if (route.type === "panel") {
    const item = findPanel(route);
    return item ? panelHash(item, filters) : "#/category/all";
  }
  if (route.type === "category") {
    const datasetId = route.datasetId || (filters.dataset !== "all" ? filters.dataset : null);
    return categoryHash(datasetId, route.subtype || "all", filters);
  }
  return withQuery("#/", filters);
}

function categoryHash(datasetId, subtype, filters = {}) {
  let path = "#/category/all";
  if (subtype && subtype !== "all") {
    path = datasetId
      ? `#/category/${encodePath(datasetId)}/${encodeURIComponent(subtype)}`
      : `#/category/${encodeURIComponent(subtype)}`;
  }
  return withQuery(path, filters);
}

function panelHash(item, filters = {}) {
  return withQuery(
    `#/panel/${encodePath(item.dataset.id)}/${encodeURIComponent(item.subtype)}/${encodeURIComponent(item.id)}`,
    filters
  );
}

function withQuery(path, filters = {}) {
  const params = new URLSearchParams();
  const normalized = normalizeFilters(filters);
  Object.entries(normalized).forEach(([key, value]) => {
    if (!value || value === DEFAULT_FILTERS[key]) {
      return;
    }
    if (key === "sort" && normalized.q && value === "relevance") {
      return;
    }
    params.set(key, value);
  });
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function normalizeFilters(filters = {}) {
  return {
    ...DEFAULT_FILTERS,
    ...filters,
    q: (filters.q || "").trim(),
  };
}

function findPanel(route) {
  if (!route.panelId) {
    return null;
  }
  return state.catalog.items.find((item) => {
    if (item.id !== route.panelId) return false;
    if (route.datasetId && item.dataset.id !== route.datasetId) return false;
    if (route.subtype && item.subtype !== route.subtype) return false;
    return true;
  }) || state.catalog.items.find((item) => item.id === route.panelId) || null;
}

function findDataset(datasetId) {
  if (!datasetId) {
    return null;
  }
  return state.catalog.datasets.find((dataset) => dataset.id === datasetId) || null;
}

function subjectSummaries() {
  const subjects = state.catalog.stats.subjects;
  if (Array.isArray(subjects) && subjects.length) {
    return subjects;
  }
  const bySubject = new Map();
  (state.catalog.datasets || []).forEach((dataset) => {
    if (!dataset.subject) return;
    const current = bySubject.get(dataset.subject) || {
      id: dataset.subject,
      panelCount: 0,
      journalCount: 0,
      datasetCount: 0,
    };
    current.panelCount += Number(dataset.panelCount || 0);
    current.journalCount += (dataset.journals || []).length;
    current.datasetCount += 1;
    bySubject.set(dataset.subject, current);
  });
  return [...bySubject.values()];
}

function subjectLabel(subject) {
  if (!subject || subject === "all") {
    return t("allDisciplines");
  }
  const labels = SUBJECT_LABELS[subject];
  if (labels) {
    return labels[state.lang] || labels.en;
  }
  return subject.split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

function activeDatasetId(route) {
  if (route && route.datasetId) {
    return route.datasetId;
  }
  if (route && route.filters && route.filters.dataset !== "all") {
    return route.filters.dataset;
  }
  return null;
}

function activeSubjectId(route) {
  const datasetId = activeDatasetId(route);
  const dataset = findDataset(datasetId);
  if (dataset && dataset.subject) {
    return dataset.subject;
  }
  if (route && route.filters && route.filters.subject !== "all") {
    return route.filters.subject;
  }
  return "all";
}

function modeLabel(route) {
  const datasetId = activeDatasetId(route);
  const dataset = findDataset(datasetId);
  if (dataset) {
    return `${subjectLabel(dataset.subject)} · ${dataset.topic || dataset.title}`;
  }
  const subject = activeSubjectId(route);
  return subject === "all" ? t("allDisciplines") : subjectLabel(subject);
}

function modeItemsForRoute(route) {
  let items = state.catalog.items || [];
  const datasetId = activeDatasetId(route);
  if (datasetId) {
    return items.filter((item) => item.dataset.id === datasetId);
  }
  const subject = activeSubjectId(route);
  if (subject !== "all") {
    items = items.filter((item) => item.dataset.subject === subject);
  }
  return items;
}

function statsForRoute(route) {
  return aggregateStats(modeItemsForRoute(route));
}

function subtypesForMode(route) {
  const counts = new Map();
  modeItemsForRoute(route).forEach((item) => {
    counts.set(item.subtype, (counts.get(item.subtype) || 0) + 1);
  });
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

function journalsForRoute(route) {
  const counts = new Map();
  baseItemsForRoute({ ...route, filters: { ...route.filters, journal: "all" } }).forEach((item) => {
    if (!item.journal) return;
    counts.set(item.journal, (counts.get(item.journal) || 0) + 1);
  });
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

function aggregateStats(items) {
  const subtypes = new Set(items.map((item) => item.subtype).filter(Boolean));
  const journals = new Set(items.map((item) => item.journal).filter(Boolean));
  const quality = items.map((item) => Number(item.qwen.overallQualityScore || 0));
  const averageQuality = quality.length
    ? quality.reduce((sum, value) => sum + value, 0) / quality.length
    : 0;
  return {
    panelCount: items.length,
    subtypeCount: subtypes.size,
    reviewPassedCount: items.filter((item) => item.review.passed).length,
    averageQuality,
    journals: [...journals].map((name) => ({ name, count: items.filter((item) => item.journal === name).length })),
  };
}

function defaultDatasetId() {
  return state.catalog.datasets[0] ? state.catalog.datasets[0].id : "biology/AI_biology";
}

function setLink(fragment, field, href) {
  const link = fragment.querySelector(`[data-field='${field}']`);
  if (link) {
    link.href = href;
  }
}

function renderMarketTile(item) {
  const preview = item.paths.targetPreview || item.paths.target;
  const refineScore = refineComplexityScore(item);
  const complexityScore = refineScore !== null
    ? `${t("refineComplexity")} ${formatScore(refineScore)}/10 · `
    : (item.complexity ? `${t("complexity")} ${formatScore(item.complexity.score)}/100 · ` : "");
  const body = `${complexityScore}${formatSubtype(item.subtype)} · ${truncate(item.caption || item.review.finalAssessment || "", 150)}`;
  return `
    <a class="market-tile" href="${panelHash(item)}">
      <span class="market-copy">
        <span class="eyebrow">${escapeHtml(t("featuredPanel"))}</span>
        <strong>${escapeHtml(paperTitle(item))}</strong>
        <span>${escapeHtml(body)}</span>
      </span>
      <span class="market-preview" aria-hidden="true">
        <img src="${attr(preview)}" alt="" loading="eager" decoding="async">
      </span>
    </a>
  `;
}

function paperTitle(item) {
  return item.doi || item.paperId || item.title || item.id;
}

function topComplexityPanels(count, route = null) {
  const items = route ? modeItemsForRoute(route) : (state.catalog.items || []);
  return items
    .filter((item) => refineComplexityScore(item) !== null || (item.complexity && Number.isFinite(Number(item.complexity.score))))
    .slice()
    .sort((a, b) => {
      const aScore = refineComplexityScore(a);
      const bScore = refineComplexityScore(b);
      const aValue = aScore !== null ? aScore : Number(a.complexity.score) / 10;
      const bValue = bScore !== null ? bScore : Number(b.complexity.score) / 10;
      return bValue - aValue || Number(b.sort.quality) - Number(a.sort.quality);
    })
    .slice(0, count);
}

function renderToolCloud() {
  const tools = [
    ["01", t("toolSearchTitle"), t("toolSearchText")],
    ["02", t("toolCompareTitle"), t("toolCompareText")],
    ["03", t("toolReviewTitle"), t("toolReviewText")],
  ];
  return `
    <div class="tool-cloud" aria-label="Gallery AI workflow">
      ${tools.map(([index, title, body]) => `
        <article class="tool-chip">
          <span>${escapeHtml(index)}</span>
          <strong>${escapeHtml(title)}</strong>
          <p>${escapeHtml(body)}</p>
        </article>
      `).join("")}
    </div>
  `;
}

function metricBlock(value, label) {
  return `<div><b>${escapeHtml(String(value))}</b><span>${escapeHtml(label)}</span></div>`;
}

function metricCard(value, label) {
  return `<div class="metric-card"><b>${escapeHtml(String(value))}</b><span>${escapeHtml(label)}</span></div>`;
}

function evidenceCard(title, body) {
  return `
    <article class="evidence-card">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(body || t("noEvidenceText"))}</p>
    </article>
  `;
}

function qwenSummary(item) {
  return t("qwenSummary", {
    overall: formatScore(item.qwen.overallQualityScore),
    clarity: formatScore(item.qwen.clarityIntegrityScore),
    purity: formatScore(item.qwen.dataPurityScore),
    code: formatScore(item.qwen.codeReproducibilityScore),
    aesthetic: formatScore(item.qwen.aestheticScore),
    complete: item.qwen.isCompletePanel ? t("yes") : t("no"),
    overlap: item.qwen.hasForeignOverlap ? t("yes") : t("no"),
    labels: item.qwen.xyLabelComplete || t("unknown"),
    ticks: item.qwen.xyTickComplete || t("unknown"),
  });
}

function figureFrame(title, previewSrc, fullSrc, alt) {
  return `
    <figure class="figure-frame">
      <h2>${escapeHtml(title)}</h2>
      <a href="${attr(fullSrc)}" target="_blank" rel="noopener" title="${attr(t("openFullSize"))}">
        <img src="${attr(previewSrc)}" alt="${attr(alt)}" loading="eager" decoding="sync">
      </a>
    </figure>
  `;
}

function metaRow(label, value) {
  if (!value) {
    return "";
  }
  return `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value))}</dd>`;
}

function assetLink(label, href) {
  if (!href) {
    return "";
  }
  const external = href.startsWith("http://") || href.startsWith("https://");
  return `<a class="data-link" href="${attr(href)}" ${external ? 'target="_blank" rel="noopener"' : ""}>${escapeHtml(label)}</a>`;
}

function option(value, label, selected) {
  return `<option value="${attr(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escapeHtml(label)}</option>`;
}

function labelForSort(sort) {
  const labels = {
    relevance: t("relevance"),
    quality: t("qualityScore"),
    review: t("reviewConfidence"),
    date: t("publicationDate"),
    subtype: t("subtype"),
    paper: t("paperDoi"),
  };
  return labels[sort] || sort;
}

function labelForReview(review) {
  const labels = {
    all: t("allReviews"),
    passed: t("passedOnly"),
    open: t("openOnly"),
  };
  return labels[review] || review;
}

function formatSubtype(subtype) {
  if (!subtype || subtype === "all") {
    return t("allChartTypes");
  }
  if (state.lang === "zh" && SUBTYPE_LABELS_ZH[subtype]) {
    return SUBTYPE_LABELS_ZH[subtype];
  }
  return subtype.split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

function formatScore(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(1);
}

function refineComplexityScore(item) {
  const score = item && item.refineComplexity ? Number(item.refineComplexity.score) : NaN;
  return Number.isFinite(score) ? score : null;
}

function panelComplexitySortValue(item) {
  const refineScore = refineComplexityScore(item);
  if (refineScore !== null) {
    return refineScore;
  }
  const visualScore = item && item.complexity ? Number(item.complexity.score) : NaN;
  return Number.isFinite(visualScore) ? visualScore / 10 : 0;
}

function formatComplexityMetric(item) {
  const refineScore = refineComplexityScore(item);
  if (refineScore !== null) {
    return `${formatScore(refineScore)}/10`;
  }
  const visualScore = item && item.complexity ? Number(item.complexity.score) : NaN;
  return Number.isFinite(visualScore) ? `${formatScore(visualScore)}/100` : t("unknown");
}

function formatNumber(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(1);
}

function truncate(value, max) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1).trim()}...` : text;
}

function encodePath(path) {
  return String(path || "").split("/").map(encodeURIComponent).join("/");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function attr(value) {
  return escapeHtml(value);
}
