"use strict";
(function () {
  const storageName = "research-platform-key";
  const keyInput = document.getElementById("api-key");
  const keyStatus = document.getElementById("key-status");
  const servingLine = document.getElementById("serving");
  const searchForm = document.getElementById("search-form");
  const searchStatus = document.getElementById("search-status");
  const results = document.getElementById("results");
  const runStatus = document.getElementById("run-status");
  const runView = document.getElementById("run-view");
  let apiKey = "";
  let serving = null;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  }

  function showError(target, error) {
    target.textContent = error instanceof Error ? error.message : "Request failed.";
  }

  async function api(method, path, body) {
    if (!apiKey) throw new Error("Enter an API key first.");
    const headers = {
      Authorization: "Bearer " + apiKey,
      Accept: "application/json"
    };
    const options = { method: method, headers: headers };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {};
    }
    if (!response.ok) {
      const detail = payload.error || {};
      throw new Error([detail.code, detail.message].filter(Boolean).join(": ") || "Request failed.");
    }
    return payload;
  }

  function restoreKey() {
    try {
      apiKey = window.sessionStorage.getItem(storageName) || "";
    } catch (_error) {
      apiKey = "";
      keyStatus.textContent = "This tab cannot access session storage; enter a key for this page.";
    }
    if (apiKey) {
      keyInput.value = apiKey;
      loadServing();
    }
  }

  async function loadServing() {
    try {
      serving = await api("GET", "/v1/serving");
      const snapshot = String(serving.snapshot_id || "");
      const generation = serving.generation === null ? "unknown" : serving.generation;
      servingLine.textContent = "snapshot " + snapshot.slice(0, 8) + "… · generation " + generation;
      keyStatus.textContent = "Connected.";
    } catch (error) {
      serving = null;
      servingLine.textContent = "Serving identity unavailable.";
      showError(keyStatus, error);
    }
  }

  function appendTable(parent, context) {
    if (!context) return;
    if (context.caption) parent.appendChild(node("p", context.caption));
    const table = node("table");
    const head = node("thead");
    (context.header_rows || []).forEach(function (row) {
      const tr = node("tr");
      (row.cells || []).forEach(function (cell) { tr.appendChild(node("th", cell.value)); });
      head.appendChild(tr);
    });
    table.appendChild(head);
    const body = node("tbody");
    (context.selected_rows || []).forEach(function (row) {
      const tr = node("tr");
      (row.cells || []).forEach(function (cell) { tr.appendChild(node("td", cell.value)); });
      body.appendChild(tr);
    });
    table.appendChild(body);
    parent.appendChild(table);
  }

  function renderEvidence(parent, hit) {
    const headings = (hit.source_spans || []).flatMap(function (span) { return span.heading_path || []; });
    if (headings.length) parent.appendChild(node("p", headings.join(" › "), "muted"));
    const page = hit.source_location && hit.source_location.page_index_zero_based;
    if (page !== null && page !== undefined) parent.appendChild(node("p", "Page " + (page + 1), "muted"));
    parent.appendChild(node("p", hit.text));
    appendTable(parent, hit.table_context);
  }

  function renderResults(payload, kind) {
    results.replaceChildren();
    searchStatus.textContent = payload.result_status + " · " + payload.eligible_count + " eligible";
    (payload.hits || []).forEach(function (hit) {
      const card = node("article", undefined, "result");
      const title = hit.title || hit.paper_id;
      card.appendChild(node("h3", "#" + hit.rank + " · " + title));
      if (hit.publication_year !== null && hit.publication_year !== undefined) {
        card.appendChild(node("p", String(hit.publication_year), "muted"));
      }
      if (kind === "evidence") renderEvidence(card, hit);
      else if (hit.supporting_evidence && hit.supporting_evidence.length) {
        renderEvidence(card, hit.supporting_evidence[0]);
      }
      results.appendChild(card);
    });
  }

  async function search(event) {
    event.preventDefault();
    searchStatus.textContent = "Searching…";
    results.replaceChildren();
    try {
      if (!serving) await loadServing();
      if (!serving) throw new Error("The serving identity is unavailable.");
      const data = new FormData(searchForm);
      const kind = data.get("kind");
      const path = kind === "evidence" ? "/v1/evidence/search" : "/v1/search";
      const payload = await api("POST", path, {
        query: data.get("query"),
        snapshot_id: serving.snapshot_id,
        retrieval_profile_id: serving.retrieval_profile_id,
        mode: "reranked",
        limit: Number(data.get("limit"))
      });
      renderResults(payload, kind);
    } catch (error) {
      showError(searchStatus, error);
    }
  }

  function paperLabel(papers, paperId) {
    const paper = (papers || []).find(function (item) { return item.paper_id === paperId; });
    if (!paper) return paperId;
    return [paper.title || paper.paper_id, paper.publication_year].filter(function (part) { return part !== null && part !== undefined; }).join(" · ");
  }

  async function loadRun() {
    const match = window.location.hash.match(/^#run=([0-9a-f-]{36})$/i);
    runView.replaceChildren();
    if (!match) {
      runStatus.textContent = "No run selected.";
      return;
    }
    runStatus.textContent = "Loading run…";
    try {
      const run = await api("GET", "/v1/research/" + match[1]);
      runStatus.textContent = run.status + (run.answer_outcome ? " · " + run.answer_outcome : "");
      runView.appendChild(node("p", "Question: " + run.question));
      if (run.failure_category) runView.appendChild(node("p", "Failure: " + run.failure_category));
      if (run.answer) runView.appendChild(node("p", run.answer));
      if (["queued", "running", "waiting_for_ingestion"].includes(run.status)) {
        const refresh = node("button", "Refresh");
        refresh.type = "button";
        refresh.addEventListener("click", loadRun);
        runView.appendChild(refresh);
      }
      (run.claims || []).forEach(function (claim) {
        const card = node("article", undefined, "claim");
        card.appendChild(node("h3", claim.text));
        card.appendChild(node("p", "Support: " + claim.support));
        if (claim.quote) {
          const quote = node("blockquote", claim.quote);
          card.appendChild(quote);
        }
        (claim.evidence || []).forEach(function (evidence) {
          card.appendChild(node("p", evidence.handle + " · " + paperLabel(run.papers, evidence.paper_id)));
        });
        runView.appendChild(card);
      });
    } catch (error) {
      showError(runStatus, error);
    }
  }

  document.getElementById("key-form").addEventListener("submit", function (event) {
    event.preventDefault();
    apiKey = keyInput.value.trim();
    try {
      if (apiKey) window.sessionStorage.setItem(storageName, apiKey);
      else window.sessionStorage.removeItem(storageName);
    } catch (_error) {
      keyStatus.textContent = "Key is available for this page only; session storage is blocked.";
    }
    loadServing();
    loadRun();
  });
  searchForm.addEventListener("submit", search);
  window.addEventListener("hashchange", loadRun);
  restoreKey();
  loadRun();
})();
