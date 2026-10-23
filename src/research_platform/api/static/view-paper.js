import { api, serving } from "./api.js";
import { h, pill } from "./dom.js";
import { onLeave } from "./router.js";
import { showResults } from "./view-search.js";

function endpointLabel(endpoint) {
  if (endpoint.status === "unresolved") {
    return {
      label: [endpoint.external_namespace, endpoint.external_identifier].filter(Boolean).join(": ") || "Unresolved citation",
      note: "not resolved",
    };
  }
  const label = [endpoint.title || endpoint.paper_id, endpoint.publication_year]
    .filter((part) => part !== null && part !== undefined)
    .join(" · ");
  return {
    label: label || endpoint.paper_id || "Paper metadata unavailable",
    note: endpoint.status === "outside_snapshot" ? "outside this collection" : "",
  };
}

function graphSection(title, direction, paperId, snapshotId, active) {
  const list = h("div", { class: "stack" });
  const message = h("p", { class: "muted", role: "status", "aria-live": "polite", text: "Loading…" });
  const section = h("section", null, h("h2", { text: title }), message, list);
  let cursor = null;
  let moreButton = null;

  async function load(append) {
    if (!append) {
      list.replaceChildren();
      message.textContent = "Loading…";
    }
    const params = new URLSearchParams({ snapshot_id: snapshotId, limit: "20" });
    if (cursor) params.set("cursor", cursor);
    try {
      const page = await api("GET", "/v1/papers/" + encodeURIComponent(paperId) + "/" + direction + "?" + params.toString());
      if (!active()) return;
      if (!append) list.replaceChildren();
      for (const edge of page.edges || []) {
        const endpoint = edge.endpoint;
        const item = endpointLabel(endpoint);
        const label = endpoint.status === "in_snapshot" && endpoint.paper_id
          ? h("a", { href: `#/papers/${encodeURIComponent(endpoint.paper_id)}`, text: item.label })
          : h("span", { text: item.label });
        list.append(h("div", { class: "row" }, label,
          item.note ? pill(item.note, endpoint.status === "unresolved" ? "warn" : "") : null));
      }
      cursor = page.has_more ? page.next_cursor : null;
      message.replaceChildren();
      if (page.has_more && cursor) {
        if (!moreButton) {
          moreButton = h("button", { class: "btn", type: "button", text: "Show more", onclick: () => {
            moreButton.disabled = true;
            void load(true);
          } });
          section.append(moreButton);
        }
        moreButton.disabled = false;
      } else if (!(page.edges || []).length && !append) {
        message.textContent = "No stored citation links were found.";
        if (moreButton) moreButton.remove();
      } else if (moreButton) {
        moreButton.remove();
        moreButton = null;
      }
    } catch (problem) {
      if (!active()) return;
      if (moreButton) moreButton.disabled = false;
      message.textContent = problem instanceof Error ? problem.message : "Could not load citation links.";
    }
  }

  void load(false);
  return section;
}

export function renderPaper(match, main) {
  let current = true;
  onLeave(() => { current = false; });
  const paperId = match[1];
  const section = h("section", { class: "doc" }, h("p", { class: "eyebrow", text: "Paper" }),
    h("h1", { text: paperId }), h("p", { class: "muted", text: "Loading paper metadata…" }));
  main.append(section);

  async function loadPaper() {
    try {
      const identity = await serving();
      const paper = await api("GET", "/v1/papers/" + encodeURIComponent(paperId) + "?snapshot_id=" + encodeURIComponent(identity.snapshot_id));
      if (!current) return;
      const title = paper.title || paper.paper_id;
      const version = paper.document_version_kind === "published" ? "published version"
        : paper.document_version_kind === "preprint" ? "preprint"
          : paper.document_version_kind || "version unavailable";
      section.replaceChildren(
        h("p", { class: "eyebrow", text: "Paper" }),
        h("h1", { class: "text-reading", text: title }),
        h("p", { class: "row muted" }, paper.publication_year ?? "Year unavailable", pill(version),
          paper.status !== "in_snapshot" ? pill("Outside this collection; metadata only", "warn") : null),
      );
      const graph = h("div", { class: "two-col" },
        graphSection("References", "references", paperId, identity.snapshot_id, () => current),
        graphSection("Cited by, in this collection", "citations", paperId, identity.snapshot_id, () => current));
      const input = h("input", { type: "search", value: title, "aria-label": "Search query" });
      const status = h("p", { class: "muted", role: "status", "aria-live": "polite" });
      const results = h("div", { class: "stack" });
      const searchForm = h("form", { class: "stack" }, h("div", { class: "field" },
        h("label", { for: "paper-query", text: "Search this paper" }), input),
        h("button", { class: "btn primary", type: "submit", text: "Search evidence" }));
      input.id = "paper-query";
      searchForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        status.textContent = "Searching this paper…";
        results.replaceChildren();
        try {
          const payload = await api("POST", "/v1/evidence/search", {
            query: input.value,
            snapshot_id: identity.snapshot_id,
            retrieval_profile_id: identity.retrieval_profile_id,
            mode: "reranked",
            limit: 10,
            filters: { paper_ids: [paperId] },
          });
          if (!current) return;
          status.replaceChildren();
          await showResults(results, payload, "evidence", identity.snapshot_id);
        } catch (problem) {
          if (!current) return;
          status.replaceChildren(pill("Search failed", "bad"), h("span", {
            text: problem instanceof Error ? problem.message : "Could not search this paper.",
          }));
        }
      });
      main.append(graph, h("section", null, searchForm, status, results));
    } catch (problem) {
      if (!current) return;
      section.replaceChildren(h("p", { class: "eyebrow", text: "Paper" }),
        h("h1", { text: paperId }), h("p", { class: "notice", text: problem instanceof Error ? problem.message : "Could not load paper metadata." }));
    }
  }

  void loadPaper();
}
