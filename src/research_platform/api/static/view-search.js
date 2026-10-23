import { api, serving } from "./api.js";
import { h, pill } from "./dom.js";
import { onLeave } from "./router.js";

const evidenceGroups = [
  { label: "Text", kinds: ["text"] },
  { label: "Tables", kinds: ["table", "table_row_group"] },
  { label: "Captions and figures", kinds: ["caption", "figure"] },
  { label: "Equations", kinds: ["equation"] },
];
const state = {
  query: "",
  kind: "papers",
  yearFrom: "",
  yearTo: "",
  limit: "10",
  kinds: Object.fromEntries(evidenceGroups.map((group) => [group.label, true])),
  payload: null,
  payloadKind: null,
  snapshotId: null,
};

export function resetSearchState() {
  state.query = "";
  state.kind = "papers";
  state.yearFrom = "";
  state.yearTo = "";
  state.limit = "10";
  state.kinds = Object.fromEntries(evidenceGroups.map((group) => [group.label, true]));
  state.payload = null;
  state.payloadKind = null;
  state.snapshotId = null;
}

function paperHref(paperId) {
  return `#/papers/${encodeURIComponent(paperId)}`;
}

function renderEvidence(parent, hit) {
  const headings = (hit.source_spans || []).flatMap((span) => span.heading_path || []);
  const page = hit.source_location && hit.source_location.page_index_zero_based;
  if (headings.length) parent.append(h("p", { class: "crumbs", text: headings.join(" › ") }));
  if (page !== null && page !== undefined) parent.append(h("p", { class: "crumbs", text: `Page ${page + 1}` }));
  if (hit.text) parent.append(h("p", { class: "text-reading", text: hit.text }));
  const context = hit.table_context;
  if (!context) return;
  const table = h("table", { class: "data" });
  if (context.header_rows && context.header_rows.length) {
    const head = h("thead", null, context.header_rows.map((row) => h("tr", null,
      row.cells.map((cell) => h("th", { text: cell.value })))));
    table.append(head);
  }
  if (context.selected_rows && context.selected_rows.length) {
    table.append(h("tbody", null, context.selected_rows.map((row) => h("tr", null,
      row.cells.map((cell) => h("td", { text: cell.value }))))));
  }
  parent.append(h("div", { class: "tablewrap stack" },
    context.caption ? h("p", { text: context.caption }) : null, table));
}

export async function showResults(parent, payload, kind, snapshotId) {
  parent.replaceChildren();
  const top = h("div", { class: "row" }, pill(payload.result_status),
    h("span", { class: "muted", text: `${payload.eligible_count} eligible before ranking` }));
  parent.append(top);
  const hits = payload.hits || [];
  if (!hits.length) {
    parent.append(h("p", { class: "muted", text: kind === "papers"
      ? "No papers matched. Remove a filter or try other words."
      : "No evidence matched. Remove a filter or try other words." }));
    return;
  }
  const metadata = new Map();
  if (kind === "evidence") {
    const paperIds = [...new Set(hits.map((hit) => hit.paper_id))];
    await Promise.all(paperIds.map(async (paperId) => {
      try {
        const paper = await api("GET", "/v1/papers/" + encodeURIComponent(paperId) + "?snapshot_id=" + encodeURIComponent(snapshotId));
        metadata.set(paperId, paper);
      } catch (_error) {
        metadata.set(paperId, null);
      }
    }));
  }
  for (const hit of hits) {
    const evidence = kind === "evidence" ? hit : (hit.supporting_evidence || [])[0];
    const paper = metadata.get(hit.paper_id);
    const title = hit.title || (paper && paper.title) || hit.paper_id;
    const year = hit.publication_year ?? (paper && paper.publication_year);
    const card = h("article", { class: "hit" },
      h("div", { class: "row" }, h("span", { class: "eyebrow", text: `#${hit.rank}` }),
        kind === "evidence" ? pill(hit.kind) : null),
      h("h2", null, h("a", { href: paperHref(hit.paper_id), text: title })),
      year !== null && year !== undefined ? h("p", { class: "muted num", text: String(year) }) : null);
    if (evidence) renderEvidence(card, evidence);
    parent.append(card);
  }
}

export function renderSearch(main) {
  let active = true;
  onLeave(() => { active = false; });
  const status = h("div", { class: "row", role: "status", "aria-live": "polite" });
  const results = h("div", { class: "stack" });
  const query = h("textarea", { id: "q", required: true, rows: "3", "aria-label": "Research query" });
  query.value = state.query;
  query.addEventListener("input", () => { state.query = query.value; });
  const yearFrom = h("input", { id: "year-from", type: "number", min: "1900", max: "2100", step: "1", inputmode: "numeric" });
  const yearTo = h("input", { id: "year-to", type: "number", min: "1900", max: "2100", step: "1", inputmode: "numeric" });
  yearFrom.value = state.yearFrom;
  yearTo.value = state.yearTo;
  yearFrom.addEventListener("input", () => { state.yearFrom = yearFrom.value; });
  yearTo.addEventListener("input", () => { state.yearTo = yearTo.value; });
  const limit = h("select", { id: "limit", "aria-label": "Result count" },
    h("option", { value: "10", text: "10 results" }), h("option", { value: "20", text: "20 results" }));
  limit.value = state.limit;
  limit.addEventListener("change", () => { state.limit = limit.value; });

  const mode = h("div", { class: "seg", role: "group", "aria-label": "Search type" });
  const papersButton = h("button", { type: "button", "aria-pressed": String(state.kind === "papers"), text: "Papers" });
  const evidenceButton = h("button", { type: "button", "aria-pressed": String(state.kind === "evidence"), text: "Evidence" });
  const checkboxArea = h("div", { class: "checkboxes" });
  for (const group of evidenceGroups) {
    const checkbox = h("input", { type: "checkbox", checked: state.kinds[group.label], "data-kind-group": group.label });
    checkbox.addEventListener("change", () => { state.kinds[group.label] = checkbox.checked; });
    checkboxArea.append(h("label", null, checkbox, group.label));
  }
  const evidenceField = h("div", { class: "field", hidden: state.kind !== "evidence" },
    h("span", { text: "Evidence types" }), checkboxArea);
  function setKind(kind) {
    state.kind = kind;
    papersButton.setAttribute("aria-pressed", String(kind === "papers"));
    evidenceButton.setAttribute("aria-pressed", String(kind === "evidence"));
    evidenceField.hidden = kind !== "evidence";
  }
  papersButton.addEventListener("click", () => setKind("papers"));
  evidenceButton.addEventListener("click", () => setKind("evidence"));
  mode.append(papersButton, evidenceButton);

  const form = h("form", { class: "stack" },
    h("div", { class: "field" }, h("label", { for: "q", text: "Research question" }), query),
    h("div", { class: "row" }, mode),
    h("div", { class: "formgrid" },
      h("div", { class: "field" }, h("label", { for: "year-from", text: "Published from" }), yearFrom),
      h("div", { class: "field" }, h("label", { for: "year-to", text: "Published to" }), yearTo),
      h("div", { class: "field" }, h("label", { for: "limit", text: "Results" }), limit)),
    evidenceField,
    h("div", { class: "row" }, h("button", { class: "btn primary", type: "submit", text: "Search" })),
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    state.query = query.value;
    state.yearFrom = yearFrom.value;
    state.yearTo = yearTo.value;
    state.limit = limit.value;
    status.replaceChildren(pill("Searching", "live"));
    results.replaceChildren();
    try {
      const identity = await serving();
      const filters = {};
      if (state.yearFrom) filters.year_from = Number(state.yearFrom);
      if (state.yearTo) filters.year_to = Number(state.yearTo);
      if (state.kind === "evidence") {
        const selectedGroups = evidenceGroups.filter((group) => state.kinds[group.label]);
        if (!selectedGroups.length) {
          throw new Error("Select at least one evidence type.");
        }
        if (selectedGroups.length !== evidenceGroups.length) {
          filters.evidence_kinds = selectedGroups.flatMap((group) => group.kinds);
        }
      }
      const path = state.kind === "evidence" ? "/v1/evidence/search" : "/v1/search";
      const payload = await api("POST", path, {
        query: state.query,
        snapshot_id: identity.snapshot_id,
        retrieval_profile_id: identity.retrieval_profile_id,
        mode: "reranked",
        limit: Number(state.limit),
        filters,
      });
      if (!active) return;
      state.payload = payload;
      state.payloadKind = state.kind;
      state.snapshotId = identity.snapshot_id;
      status.replaceChildren(pill(payload.result_status));
      await showResults(results, payload, state.payloadKind, identity.snapshot_id);
    } catch (problem) {
      if (!active) return;
      const message = problem instanceof Error ? problem.message : "Search failed. Try another query or remove a filter.";
      status.replaceChildren(pill("Search failed", "bad"), h("span", {
        text: `${message} Check the key, adjust the query or remove a filter, then retry.`,
      }));
    }
  });

  const identityLine = h("span", { class: "muted", text: "Using the configured collection." });
  void serving().then((identity) => {
    if (active) identityLine.textContent = `snapshot ${String(identity.snapshot_id).slice(0, 8)} · generation ${identity.generation ?? "unknown"}`;
  }).catch(() => {
    if (active) identityLine.textContent = "Serving identity unavailable.";
  });
  main.append(h("section", { class: "doc" },
    h("div", { class: "searchhead" }, h("h1", { text: "Search the collection" }), identityLine),
    form, status, results));
  if (state.payload) {
    status.replaceChildren(pill(state.payload.result_status));
    void serving().then((identity) => showResults(
      results,
      state.payload,
      state.payloadKind || state.kind,
      state.snapshotId || identity.snapshot_id,
    )).catch(() => {});
  }
}
