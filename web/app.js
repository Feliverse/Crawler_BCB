const state = {
  rawData: {},
  selectedUrl: "",
  data: {},
  rootLabel: "",
  rootNode: {},
  activePath: [],
  query: "",
  dateFilter: "all"
};

const elements = {};

function bindElements() {
  elements.fileInput = document.getElementById("fileInput");
  elements.reloadButton = document.getElementById("reloadButton");
  elements.urlSelector = document.getElementById("urlSelector");
  elements.urlSelectorWrapper = document.getElementById("urlSelectorWrapper");
  elements.searchInput = document.getElementById("searchInput");
  elements.dateFilter = document.getElementById("dateFilter");
  elements.categoryList = document.getElementById("categoryList");
  elements.categoryCount = document.getElementById("categoryCount");
  elements.detailTitle = document.getElementById("detailTitle");
  elements.detailSubtitle = document.getElementById("detailSubtitle");
  elements.detailBadge = document.getElementById("detailBadge");
  elements.detailContent = document.getElementById("detailContent");
  elements.metricCategories = document.getElementById("metricCategories");
  elements.metricSections = document.getElementById("metricSections");
  elements.metricDocuments = document.getElementById("metricDocuments");
  elements.metricMatches = document.getElementById("metricMatches");
  elements.breadcrumb = document.getElementById("breadcrumb");
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isDocumentLeaf(node) {
  return isPlainObject(node)
    && typeof node.descripcion === "string"
    && typeof node.url_descarga === "string";
}

function normalizeText(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
}

function prettyLabel(value) {
  if (value === undefined || value === null) {
    return "";
  }

  const raw = String(value);

  try {
    return decodeURIComponent(raw)
      .replace(/_/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  } catch {
    return raw.replace(/_/g, " ").replace(/\s+/g, " ").trim();
  }
}

function resolveRoot(data) {
  if (isPlainObject(data?.ESTADISTICAS)) {
    return { label: "ESTADISTICAS", node: data.ESTADISTICAS };
  }

  const entries = Object.entries(data || {});
  if (!entries.length) {
    return { label: "", node: {} };
  }

  const [firstLabel, firstNode] = entries[0];
  return { label: firstLabel, node: isPlainObject(firstNode) ? firstNode : {} };
}

function getRootEntries() {
  return Object.entries(state.rootNode || {});
}

function getNodeAtPath(path) {
  let node = state.rootNode;

  for (const key of path) {
    if (!isPlainObject(node)) {
      return null;
    }
    node = node[key];
  }

  return node || null;
}

function countDocuments(node) {
  if (isDocumentLeaf(node)) {
    return 1;
  }

  if (!isPlainObject(node)) {
    return 0;
  }

  let total = 0;
  for (const child of Object.values(node)) {
    total += countDocuments(child);
  }
  return total;
}

function countBranches(node) {
  if (isDocumentLeaf(node) || !isPlainObject(node)) {
    return 0;
  }

  let total = 1;
  for (const child of Object.values(node)) {
    total += countBranches(child);
  }
  return total;
}

function docMatchesFilters(doc, pathLabels) {
  const query = normalizeText(state.query);

  if (state.dateFilter === "updated") {
    if (!doc.fecha_actualizacion || doc.fecha_actualizacion === "No disponible") {
      return false;
    }
  }

  if (state.dateFilter === "missing") {
    if (doc.fecha_actualizacion && doc.fecha_actualizacion !== "No disponible") {
      return false;
    }
  }

  if (!query) {
    return true;
  }

  const haystack = normalizeText([
    pathLabels.join(" "),
    doc.descripcion,
    doc.url_descarga,
    doc.fecha_actualizacion
  ].join(" "));

  return haystack.includes(query);
}

function countMatchingDocuments(node, pathLabels = []) {
  if (isDocumentLeaf(node)) {
    return docMatchesFilters(node, pathLabels) ? 1 : 0;
  }

  if (!isPlainObject(node)) {
    return 0;
  }

  let total = 0;
  for (const [key, child] of Object.entries(node)) {
    total += countMatchingDocuments(child, [...pathLabels, prettyLabel(key)]);
  }
  return total;
}

function createBadge(text, colorClasses = "bg-stone-200 text-stone-700") {
  const badge = document.createElement("span");
  badge.className = `inline-flex items-center rounded-full px-3 py-1 text-xs font-bold ${colorClasses}`;
  badge.textContent = text;
  return badge;
}

function createDocCard(doc, pathLabels) {
  const card = document.createElement("article");
  card.className = "rounded-3xl border border-stone-200 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-clay/25 hover:shadow-md";

  const header = document.createElement("div");
  header.className = "flex flex-wrap items-start justify-between gap-3";

  const titleWrap = document.createElement("div");
  titleWrap.className = "min-w-0 flex-1";

  const title = document.createElement("h4");
  title.className = "text-sm font-extrabold text-ink sm:text-base";
  title.textContent = doc.descripcion || "Documento sin titulo";

  const meta = document.createElement("p");
  meta.className = "mt-1 text-xs leading-5 text-stone-500";
  meta.textContent = pathLabels.filter(Boolean).join(" · ");

  titleWrap.append(title, meta);

  const link = document.createElement("a");
  link.className = "rounded-full border border-clay/20 bg-clay/10 px-3 py-2 text-xs font-bold text-clay transition hover:bg-clay/15";
  link.href = doc.url_descarga;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "Abrir";

  header.append(titleWrap, link);

  const footer = document.createElement("div");
  footer.className = "mt-3 flex flex-wrap items-center gap-2";
  footer.append(createBadge(doc.fecha_actualizacion && doc.fecha_actualizacion !== "No disponible" ? doc.fecha_actualizacion : "Sin fecha", "bg-tealstone/10 text-tealstone"));
  footer.append(createBadge(doc.url_descarga.endsWith(".xlsx") || doc.url_descarga.endsWith(".xls") ? "Excel" : doc.url_descarga.endsWith(".csv") ? "CSV" : "Enlace", "bg-stone-100 text-stone-700"));

  card.append(header, footer);
  return card;
}

function renderBranch(node, path = [], depth = 0, labelPath = []) {
  if (isDocumentLeaf(node)) {
    return docMatchesFilters(node, labelPath) ? createDocCard(node, labelPath) : null;
  }

  if (!isPlainObject(node)) {
    return null;
  }

  const visibleChildren = [];
  for (const [key, child] of Object.entries(node)) {
    const childPath = [...path, key];
    const childLabelPath = [...labelPath, prettyLabel(key)];
    const childVisibleCount = countMatchingDocuments(child, childLabelPath);
    if (childVisibleCount > 0) {
      visibleChildren.push({ key, child, childPath, childLabelPath, childVisibleCount });
    }
  }

  if (!visibleChildren.length) {
    return null;
  }

  const section = document.createElement("section");
  section.className = "rounded-[1.75rem] border border-stone-200 bg-white/90 p-4 shadow-sm sm:p-5";

  const head = document.createElement("div");
  head.className = "flex flex-wrap items-start justify-between gap-3";

  const headCopy = document.createElement("div");

  const title = document.createElement("h3");
  title.className = depth === 0 ? "text-xl font-extrabold tracking-tight text-ink" : "text-lg font-extrabold tracking-tight text-ink";
  title.textContent = labelPath[labelPath.length - 1] || state.rootLabel || "Raiz";

  const subtitle = document.createElement("p");
  subtitle.className = "mt-1 text-sm text-stone-500";
  subtitle.textContent = `${visibleChildren.length} ramas visibles · ${countMatchingDocuments(node, labelPath)} documentos`;

  headCopy.append(title, subtitle);

  const actions = document.createElement("div");
  actions.className = "flex flex-wrap items-center gap-2";

  if (path.length) {
    const focusButton = document.createElement("button");
    focusButton.type = "button";
    focusButton.className = "rounded-full border border-stone-200 bg-stone-100 px-3 py-2 text-xs font-bold text-stone-700 transition hover:border-clay/25 hover:text-clay";
    focusButton.textContent = "Abrir esta rama";
    focusButton.addEventListener("click", () => {
      state.activePath = [...path];
      render();
    });
    actions.append(focusButton);
  }

  actions.append(createBadge(`${countMatchingDocuments(node, labelPath)} docs`, "bg-tealstone/10 text-tealstone"));

  head.append(headCopy, actions);
  section.appendChild(head);

  const body = document.createElement("div");
  body.className = "mt-4 grid gap-3";

  for (const { key, child, childPath, childLabelPath, childVisibleCount } of visibleChildren) {
    if (isDocumentLeaf(child)) {
      body.appendChild(createDocCard(child, childLabelPath));
      continue;
    }

    const childCard = document.createElement("div");
    childCard.className = "rounded-[1.5rem] border border-stone-200 bg-stone-50 p-3 sm:p-4";

    const childHead = document.createElement("div");
    childHead.className = "flex flex-wrap items-start justify-between gap-3";

    const childTitleWrap = document.createElement("div");
    const childTitle = document.createElement("h4");
    childTitle.className = "text-sm font-extrabold text-ink sm:text-base";
    childTitle.textContent = prettyLabel(key);

    const childMeta = document.createElement("p");
    childMeta.className = "mt-1 text-xs text-stone-500";
    childMeta.textContent = childPath.filter(Boolean).join(" · ");

    childTitleWrap.append(childTitle, childMeta);

    const childButtons = document.createElement("div");
    childButtons.className = "flex items-center gap-2";

    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "rounded-full border border-clay/20 bg-clay/10 px-3 py-2 text-xs font-bold text-clay transition hover:bg-clay/15";
    openButton.textContent = "Abrir";
    openButton.addEventListener("click", () => {
      state.activePath = [...childPath];
      render();
    });

    childButtons.append(openButton, createBadge(`${childVisibleCount} docs`, "bg-stone-200 text-stone-700"));
    childHead.append(childTitleWrap, childButtons);

    childCard.appendChild(childHead);

    const nested = renderBranch(child, childPath, depth + 1, childLabelPath);
    if (nested) {
      const nestedWrap = document.createElement("div");
      nestedWrap.className = "mt-3 grid gap-3 pl-0 sm:pl-2";
      nestedWrap.appendChild(nested);
      childCard.appendChild(nestedWrap);
    }

    body.appendChild(childCard);
  }

  section.appendChild(body);
  return section;
}

function buildBreadcrumb(path) {
  elements.breadcrumb.innerHTML = "";

  if (!path.length) {
    const empty = document.createElement("span");
    empty.textContent = "Raiz";
    elements.breadcrumb.appendChild(empty);
    return;
  }

  const rootChip = document.createElement("button");
  rootChip.type = "button";
  rootChip.className = "rounded-full bg-tealstone/10 px-3 py-1.5 font-bold text-tealstone transition hover:bg-tealstone/15";
  rootChip.textContent = state.rootLabel || "Raiz";
  rootChip.addEventListener("click", () => {
    state.activePath = [path[0]];
    render();
  });
  elements.breadcrumb.appendChild(rootChip);

  for (let index = 0; index < path.length; index += 1) {
    const separator = document.createElement("span");
    separator.className = "text-stone-400";
    separator.textContent = "/";
    elements.breadcrumb.appendChild(separator);

    const label = prettyLabel(path[index]);
    if (index === path.length - 1) {
      const current = document.createElement("span");
      current.className = "rounded-full bg-stone-200 px-3 py-1.5 font-bold text-stone-700";
      current.textContent = label;
      elements.breadcrumb.appendChild(current);
      continue;
    }

    const crumb = document.createElement("button");
    crumb.type = "button";
    crumb.className = "rounded-full bg-stone-100 px-3 py-1.5 font-semibold text-stone-600 transition hover:bg-stone-200";
    crumb.textContent = label;
    crumb.addEventListener("click", () => {
      state.activePath = path.slice(0, index + 1);
      render();
    });
    elements.breadcrumb.appendChild(crumb);
  }
}

function renderCategoryList() {
  const entries = getRootEntries();
  const filtered = entries.filter(([key, child]) => countMatchingDocuments(child, [prettyLabel(key)]) > 0);

  elements.categoryList.innerHTML = "";
  elements.categoryCount.textContent = String(filtered.length);

  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "rounded-2xl border border-dashed border-stone-200 bg-stone-50 p-4 text-sm text-stone-500";
    empty.textContent = "No hay coincidencias con el filtro actual.";
    elements.categoryList.appendChild(empty);
    return;
  }

  for (const [key, child] of filtered) {
    const path = [key];
    const docs = countMatchingDocuments(child, [prettyLabel(key)]);
    const active = state.activePath[0] === key;

    const button = document.createElement("button");
    button.type = "button";
    button.className = [
      "w-full rounded-[1.5rem] border p-4 text-left transition",
      active ? "border-clay/30 bg-clay/10 shadow-sm" : "border-stone-200 bg-white hover:border-clay/20 hover:bg-stone-50"
    ].join(" ");

    button.innerHTML = `
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <h3 class="truncate text-base font-extrabold text-ink">${escapeHtml(prettyLabel(key))}</h3>
          <p class="mt-1 text-sm text-stone-500">${countBranches(child)} nodos · ${docs} documentos</p>
        </div>
        <span class="rounded-full ${active ? 'bg-clay text-white' : 'bg-stone-200 text-stone-700'} px-3 py-1 text-xs font-bold">${docs}</span>
      </div>
    `;

    button.addEventListener("click", () => {
      state.activePath = path;
      render();
    });

    elements.categoryList.appendChild(button);
  }
}

function getTotals() {
  const entries = getRootEntries();
  const categories = entries.length;
  const nodes = entries.reduce((total, [, child]) => total + countBranches(child), 0);
  const documents = entries.reduce((total, [, child]) => total + countDocuments(child), 0);
  return { categories, nodes, documents };
}

function render() {
  const totals = getTotals();
  const selectedNode = getNodeAtPath(state.activePath);
  const selectedPathLabels = state.activePath.map(prettyLabel);

  elements.metricCategories.textContent = String(totals.categories);
  elements.metricSections.textContent = String(totals.nodes);
  elements.metricDocuments.textContent = String(totals.documents);

  renderCategoryList();

  if (!selectedNode) {
    elements.detailTitle.textContent = "Sin datos";
    elements.detailSubtitle.textContent = "Carga un archivo JSON para comenzar.";
    elements.detailBadge.textContent = "0 documentos";
    elements.metricMatches.textContent = "0";
    elements.breadcrumb.innerHTML = "";
    elements.detailContent.innerHTML = '<div class="rounded-3xl border border-dashed border-stone-200 bg-stone-50 p-6 text-sm text-stone-500">No se encontró la categoría seleccionada.</div>';
    return;
  }

  const visibleDocuments = countMatchingDocuments(selectedNode, selectedPathLabels);
  elements.metricMatches.textContent = String(visibleDocuments);
  elements.detailTitle.textContent = selectedPathLabels[selectedPathLabels.length - 1] || state.rootLabel || "Raiz";
  elements.detailSubtitle.textContent = `${selectedPathLabels.join(" · ") || state.rootLabel} · vista jerárquica del JSON`;
  elements.detailBadge.textContent = `${visibleDocuments} documentos`;

  buildBreadcrumb(state.activePath);

  const content = renderBranch(selectedNode, state.activePath, 0, selectedPathLabels);
  elements.detailContent.innerHTML = "";

  if (!content) {
    const empty = document.createElement("div");
    empty.className = "rounded-3xl border border-dashed border-stone-200 bg-stone-50 p-6 text-sm text-stone-500";
    empty.textContent = "No hay documentos visibles para el filtro actual.";
    elements.detailContent.appendChild(empty);
    return;
  }

  elements.detailContent.appendChild(content);
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function loadDefaultJson() {
  const response = await fetch("../super_output.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`No se pudo cargar el JSON por defecto (${response.status})`);
  }
  return response.json();
}

async function loadFromFile(file) {
  const text = await file.text();
  return JSON.parse(text);
}

function applyData(data) {
  state.rawData = data || {};
  
  const urls = Object.keys(state.rawData);
  if (urls.length > 0 && isPlainObject(state.rawData[urls[0]]) && 'data' in state.rawData[urls[0]]) {
    // New super_output.json format
    elements.urlSelector.innerHTML = "";
    urls.forEach(url => {
      const opt = document.createElement("option");
      opt.value = url;
      opt.textContent = url.replace('https://www.', '').replace('http://www.', '');
      elements.urlSelector.appendChild(opt);
    });
    elements.urlSelectorWrapper.classList.remove("hidden");
    selectUrl(urls[0]);
  } else {
    // Legacy single-site format
    elements.urlSelectorWrapper.classList.add("hidden");
    state.data = isPlainObject(data) ? data : {};
    const root = resolveRoot(state.data);
    state.rootLabel = root.label;
    state.rootNode = root.node;

    const firstEntry = getRootEntries()[0];
    state.activePath = firstEntry ? [firstEntry[0]] : [];
    render();
  }
}

function selectUrl(url) {
  state.selectedUrl = url;
  if (elements.urlSelector.value !== url) {
    elements.urlSelector.value = url;
  }
  
  const urlData = state.rawData[url] || {};
  state.data = urlData.data || {};
  
  const root = resolveRoot(state.data);
  state.rootLabel = root.label;
  state.rootNode = root.node;

  const firstEntry = getRootEntries()[0];
  state.activePath = firstEntry ? [firstEntry[0]] : [];
  render();
}

function initEvents() {
  if (elements.urlSelector) {
    elements.urlSelector.addEventListener("change", (event) => {
      selectUrl(event.target.value);
    });
  }

  elements.searchInput.addEventListener("input", (event) => {
    state.query = event.target.value;
    render();
  });

  elements.dateFilter.addEventListener("change", (event) => {
    state.dateFilter = event.target.value;
    render();
  });

  elements.fileInput.addEventListener("change", async (event) => {
    const [file] = event.target.files || [];
    if (!file) {
      return;
    }

    try {
      const data = await loadFromFile(file);
      applyData(data);
    } catch (error) {
      console.error(error);
      alert("No se pudo leer el JSON seleccionado. Verifica que el archivo sea valido.");
    }
  });

  elements.reloadButton.addEventListener("click", async () => {
    try {
      const data = await loadDefaultJson();
      applyData(data);
    } catch (error) {
      console.error(error);
      alert("No se pudo cargar el JSON por defecto. Usa la carga manual si abres la página fuera de un servidor local.");
    }
  });
}

async function bootstrap() {
  bindElements();
  initEvents();

  try {
    const data = await loadDefaultJson();
    applyData(data);
  } catch (error) {
    console.warn("Carga por defecto fallida, esperando archivo local.", error);
    render();
  }
}

document.addEventListener("DOMContentLoaded", bootstrap);