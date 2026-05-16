// Havocforge demo — vanilla JS, no build step.
//
// Loads the schema list and op catalog from the API on init, wires up the
// controls, and renders a side-by-side JSON diff when the user clicks Generate.

(() => {
  "use strict";

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const themeBtn = $("theme-toggle");
  const schemaSel = $("schema-select");
  const countRange = $("count-range");
  const countOut = $("count-output");
  const seedInput = $("seed-input");
  const opsGrid = $("ops-grid");
  const generateBtn = $("generate-btn");
  const copyCurlBtn = $("copy-curl-btn");
  const copyJsonBtn = $("copy-json-btn");
  const statusPills = $("status-pills");
  const comparison = $("comparison");
  const cleanOut = $("clean-out");
  const chaosOut = $("chaos-out");
  const responseDetails = $("response-details");
  const chaosAppliedList = $("chaos-applied");
  const responseHeadersOut = $("response-headers");
  const explainer = $("explainer");
  const curlPreview = $("curl-preview");
  const repoLink = $("repo-link");

  let lastResult = null;
  let opCatalog = null;
  const REPO_URL = "https://github.com/psarchi/havocforge";

  repoLink.href = REPO_URL;

  // ── Theme ─────────────────────────────────────────────────────────────────

  const THEME_KEY = "havocforge.theme";
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    themeBtn.textContent = theme === "dark" ? "light" : "dark";
  }
  applyTheme(localStorage.getItem(THEME_KEY) || "dark");
  themeBtn.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });

  // ── Controls ──────────────────────────────────────────────────────────────

  countRange.addEventListener("input", () => { countOut.textContent = countRange.value; });

  // ── Init: load schemas + op catalog in parallel ──────────────────────────

  async function init() {
    try {
      const [schemasRes, opsRes] = await Promise.all([
        fetch("/api/schemas").then((r) => r.json()),
        fetch("/api/ops").then((r) => r.json()),
      ]);
      populateSchemas(schemasRes.schemas);
      opCatalog = opsRes.categories;
      renderOps(opCatalog);
      updateCurlPreview();
    } catch (e) {
      explainer.textContent = "Failed to load demo data: " + e.message;
    }
  }

  function populateSchemas(schemas) {
    schemaSel.innerHTML = "";
    for (const s of schemas) {
      const opt = document.createElement("option");
      opt.value = s.name;
      opt.textContent = `${s.label} (${s.field_count} fields)`;
      schemaSel.appendChild(opt);
    }
    schemaSel.addEventListener("change", updateCurlPreview);
  }

  function renderOps(categories) {
    opsGrid.innerHTML = "";
    const order = ["body", "status", "server", "header", "streaming", "drift"];
    for (const cat of order) {
      const ops = categories[cat] || [];
      if (!ops.length) continue;

      const wrap = document.createElement("div");
      wrap.className = "op-cat";

      const head = document.createElement("div");
      head.className = "op-cat-head";
      head.innerHTML = `${cat}<span class="count">(${ops.length})</span>`;
      wrap.appendChild(head);

      const ul = document.createElement("ul");
      ul.className = "op-list";
      for (const op of ops) {
        const li = document.createElement("li");
        if (!op.available) li.classList.add("op-disabled");

        const label = document.createElement("label");
        label.title = op.disabled_reason || "";

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = op.name;
        cb.dataset.op = op.name;
        cb.dataset.available = op.available ? "1" : "0";
        cb.addEventListener("change", onOpToggle);

        const name = document.createElement("span");
        name.textContent = op.name;

        label.appendChild(cb);
        label.appendChild(name);
        li.appendChild(label);
        ul.appendChild(li);
      }
      wrap.appendChild(ul);
      opsGrid.appendChild(wrap);
    }
  }

  function onOpToggle(e) {
    const cb = e.target;
    if (cb.checked && cb.dataset.available === "0") {
      cb.checked = false;
      const reason = cb.closest("label").title || "Not available in the demo.";
      flashStatus(`${cb.dataset.op}: ${reason}`, "bad", 5000);
    }
    updateCurlPreview();
  }

  // ── Build the request URL + curl preview ─────────────────────────────────

  function selectedOps() {
    return Array.from(opsGrid.querySelectorAll('input[type="checkbox"]:checked'))
      .map((cb) => cb.value);
  }

  function buildQuery() {
    const params = new URLSearchParams();
    params.set("schema", schemaSel.value || "smoke");
    params.set("count", countRange.value);
    if (seedInput.value) params.set("seed", seedInput.value);
    const ops = selectedOps();
    if (ops.length) params.set("chaos_ops", ops.join(","));
    return params;
  }

  function updateCurlPreview() {
    const url = `${window.location.origin}/api/generate?${buildQuery().toString()}`;
    curlPreview.textContent = `$ curl "${url}"`;
  }

  // ── Generate ──────────────────────────────────────────────────────────────

  generateBtn.addEventListener("click", async () => {
    generateBtn.disabled = true;
    generateBtn.textContent = "Generating…";
    statusPills.innerHTML = "";
    try {
      const res = await fetch(`/api/generate?${buildQuery().toString()}`);
      const text = await res.text();
      let body;
      try { body = JSON.parse(text); } catch { body = { error: "non-json response", raw: text }; }

      if (!res.ok) {
        renderError(res.status, body);
        return;
      }
      lastResult = body;
      render(body);
    } catch (e) {
      renderError(0, { error: e.message });
    } finally {
      generateBtn.disabled = false;
      generateBtn.textContent = "Generate →";
    }
  });

  function renderError(status, body) {
    comparison.hidden = false;
    cleanOut.textContent = "";
    chaosOut.textContent = JSON.stringify(body, null, 2);
    flashStatus(`error ${status || "(network)"}: ${body.detail?.reason || body.error || body.detail || "see response"}`, "err", 6000);
    responseDetails.hidden = true;
  }

  // ── Render the comparison ────────────────────────────────────────────────

  function render(body) {
    comparison.hidden = false;

    const clean = body.clean;
    const chaos = body.chaos;

    // Compute per-path diff against clean.items vs chaos.items
    const diffPaths = computeDiffPaths(clean.items, chaos.items);

    cleanOut.innerHTML = renderJson(clean.items, [], diffPaths, /*highlightSide=*/ "left");
    chaosOut.innerHTML = renderJson(chaos.items, [], diffPaths, /*highlightSide=*/ "right");

    // Status / latency / chaos-fired pills
    statusPills.innerHTML = "";
    addPill(`HTTP ${chaos.status}`, chaos.status >= 400 ? "err" : (chaos.status >= 300 ? "bad" : "ok"));
    addPill(`clean: ${clean.elapsed_ms}ms`, "ok");
    addPill(`chaos: ${chaos.elapsed_ms}ms`, chaos.elapsed_ms - clean.elapsed_ms > 50 ? "bad" : "ok");
    if (chaos.chaos_applied?.length) addPill(`${chaos.chaos_applied.length} ops fired`, "ok");

    // Response details
    chaosAppliedList.innerHTML = "";
    for (const desc of chaos.chaos_applied || []) {
      const li = document.createElement("li");
      li.textContent = desc;
      chaosAppliedList.appendChild(li);
    }
    if (Object.keys(chaos.headers || {}).length) {
      responseHeadersOut.textContent = JSON.stringify(chaos.headers, null, 2);
    } else {
      responseHeadersOut.textContent = "(none)";
    }
    responseDetails.hidden = false;

    // Explainer line
    const ops = body.request.ops || [];
    const fieldCount = diffPaths.size;
    if (!ops.length) {
      explainer.className = "explainer muted";
      explainer.innerHTML = "No chaos ops selected — both sides identical. Pick one or more ops above and click <em>Generate</em> again.";
    } else {
      explainer.className = "explainer dynamic";
      explainer.innerHTML = `${ops.length} op${ops.length === 1 ? "" : "s"} requested · ${chaos.chaos_applied.length} fire${chaos.chaos_applied.length === 1 ? "" : "s"} recorded · ${fieldCount} field path${fieldCount === 1 ? "" : "s"} differ across ${chaos.items.length} record${chaos.items.length === 1 ? "" : "s"}.`;
    }
  }

  function addPill(text, kind) {
    const span = document.createElement("span");
    span.className = "pill " + (kind || "");
    span.textContent = text;
    statusPills.appendChild(span);
  }

  function flashStatus(text, kind, ms) {
    statusPills.innerHTML = "";
    addPill(text, kind);
    if (ms) setTimeout(() => { if (statusPills.firstChild?.textContent === text) statusPills.innerHTML = ""; }, ms);
  }

  // ── Diff computation ──────────────────────────────────────────────────────
  // Walk both arrays/objects in parallel, recording paths where leaf values
  // differ. Path keys are JSON-style strings: "0.email", "2.profile.age".

  function computeDiffPaths(a, b) {
    const paths = new Set();
    walkDiff(a, b, [], paths);
    return paths;
  }

  function walkDiff(a, b, path, out) {
    if (a === b) return;
    if (typeof a !== typeof b || a === null || b === null) {
      out.add(path.join("."));
      return;
    }
    if (Array.isArray(a) && Array.isArray(b)) {
      const n = Math.max(a.length, b.length);
      for (let i = 0; i < n; i++) walkDiff(a[i], b[i], path.concat(i), out);
      return;
    }
    if (typeof a === "object") {
      const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
      for (const k of keys) walkDiff(a[k], b[k], path.concat(k), out);
      return;
    }
    out.add(path.join("."));
  }

  // ── JSON rendering with diff highlighting ────────────────────────────────

  function renderJson(value, path, diffPaths, side) {
    return jsonNode(value, path, diffPaths, "", side);
  }

  function jsonNode(value, path, diffPaths, indent, side) {
    if (value === null) return wrapDiff('<span class="json-null">null</span>', path, diffPaths);
    if (typeof value === "boolean") return wrapDiff(`<span class="json-bool">${value}</span>`, path, diffPaths);
    if (typeof value === "number") return wrapDiff(`<span class="json-num">${value}</span>`, path, diffPaths);
    if (typeof value === "string") return wrapDiff(`<span class="json-str">${escapeStr(value)}</span>`, path, diffPaths);
    if (Array.isArray(value)) {
      if (!value.length) return wrapDiff('<span class="json-punc">[]</span>', path, diffPaths);
      const inner = value.map((v, i) =>
        `${indent}  ${jsonNode(v, path.concat(i), diffPaths, indent + "  ", side)}`
      ).join(",\n");
      return `<span class="json-punc">[</span>\n${inner}\n${indent}<span class="json-punc">]</span>`;
    }
    if (typeof value === "object") {
      const keys = Object.keys(value);
      if (!keys.length) return '<span class="json-punc">{}</span>';
      const inner = keys.map((k) => {
        const childPath = path.concat(k);
        const child = jsonNode(value[k], childPath, diffPaths, indent + "  ", side);
        return `${indent}  <span class="json-key">"${escapeKey(k)}"</span><span class="json-punc">:</span> ${child}`;
      }).join(",\n");
      return `<span class="json-punc">{</span>\n${inner}\n${indent}<span class="json-punc">}</span>`;
    }
    return String(value);
  }

  function wrapDiff(html, path, diffPaths) {
    const key = path.join(".");
    if (diffPaths.has(key)) return `<span class="json-diff">${html}</span>`;
    return html;
  }

  const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  function escapeStr(s) {
    return `"${String(s).replace(/[&<>"']/g, (c) => HTML_ESCAPES[c])}"`;
  }
  function escapeKey(s) {
    return String(s).replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
  }

  // ── Copy buttons ──────────────────────────────────────────────────────────

  copyCurlBtn.addEventListener("click", async () => {
    const url = `${window.location.origin}/api/generate?${buildQuery().toString()}`;
    await navigator.clipboard.writeText(`curl "${url}"`);
    flashStatus("copied curl", "ok", 1500);
  });

  copyJsonBtn.addEventListener("click", async () => {
    if (!lastResult) {
      flashStatus("no JSON yet — click Generate first", "bad", 2500);
      return;
    }
    await navigator.clipboard.writeText(JSON.stringify(lastResult.chaos.items, null, 2));
    flashStatus("copied JSON (chaos side)", "ok", 1500);
  });

  // ── Boot ──────────────────────────────────────────────────────────────────

  init();
})();
