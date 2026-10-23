import { api } from "./api.js";
import { fmtSeconds, h } from "./dom.js";
import { onLeave } from "./router.js";
import { statusPill } from "./run-record.js";

function localDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

export function renderRuns(main) {
  let active = true;
  let cursor = null;
  let loading = false;
  onLeave(() => { active = false; });
  const rows = h("tbody");
  const status = h("p", { class: "muted", role: "status", "aria-live": "polite", text: "Loading runs…" });
  const more = h("button", { class: "btn", type: "button", text: "Show more", hidden: true });
  const table = h("table", { class: "data runs-table" },
    h("thead", null, h("tr", null,
      h("th", { scope: "col", text: "Status" }),
      h("th", { scope: "col", text: "Question" }),
      h("th", { scope: "col", text: "Mode" }),
      h("th", { scope: "col", text: "Started" }),
      h("th", { scope: "col", text: "Time" }))), rows);
  const empty = h("p", { class: "muted", hidden: true }, "No runs yet. ", h("a", { href: "#/new", text: "Start one" }));

  function appendRun(run) {
    rows.append(h("tr", null,
      h("td", null, statusPill(run)),
      h("td", null, h("a", { href: `#/runs/${run.run_id}`, text: run.question })),
      h("td", { text: run.mode === "deep_research" ? "Deep research" : "Quick" }),
      h("td", { text: localDate(run.created_at) }),
      h("td", { class: "num", text: fmtSeconds(run.active_seconds || 0) })));
  }

  async function loadPage(next = false) {
    if (loading || !active) return;
    loading = true;
    more.disabled = true;
    status.textContent = next ? "Loading more runs…" : "Loading runs…";
    try {
      const query = new URLSearchParams({ limit: "20" });
      if (next && cursor) query.set("cursor", cursor);
      const page = await api("GET", `/v1/research?${query.toString()}`);
      if (!active) return;
      page.runs.forEach(appendRun);
      cursor = page.next_cursor;
      more.hidden = !cursor;
      empty.hidden = rows.children.length > 0;
      status.textContent = rows.children.length ? `${rows.children.length} runs shown.` : "";
    } catch (problem) {
      if (active) status.textContent = problem instanceof Error ? problem.message : "Could not load runs.";
    } finally {
      loading = false;
      more.disabled = false;
    }
  }
  more.addEventListener("click", () => { void loadPage(true); });
  main.append(h("section", { class: "doc stack" },
    h("div", { class: "spread" }, h("h1", { text: "Your research runs" }),
      h("a", { class: "btn primary", href: "#/new", text: "New run" })),
    status, empty, h("div", { class: "tablewrap" }, table), more));
  void loadPage();
}
