import { api } from "./api.js";
import { h, pill } from "./dom.js";
import { onLeave } from "./router.js";

function paperLabel(papers, paperId) {
  const paper = (papers || []).find((item) => item.paper_id === paperId);
  if (!paper) return paperId;
  return [paper.title || paper.paper_id, paper.publication_year]
    .filter((part) => part !== null && part !== undefined)
    .join(" · ");
}

export function renderRun(match, main) {
  let active = true;
  onLeave(() => { active = false; });
  const id = match[1];
  const status = h("p", { class: "muted", role: "status", "aria-live": "polite", text: "Loading run…" });
  const content = h("div", { class: "stack" });
  main.append(h("section", { class: "doc" }, h("p", { class: "eyebrow", text: "Research run" }),
    h("h1", { text: "Run details" }), status, content));

  async function loadRun() {
    status.textContent = "Loading run…";
    try {
      const run = await api("GET", "/v1/research/" + id);
      if (!active) return;
      status.replaceChildren(pill(run.status, ["queued", "running", "waiting_for_ingestion"].includes(run.status) ? "live" : ""));
      if (run.answer_outcome) status.append(" · ", run.answer_outcome);
      content.replaceChildren();
      content.append(h("section", null, h("h2", { text: "Question" }), h("p", { class: "text-reading", text: run.question })));
      if (run.failure_category) content.append(h("p", { class: "notice", text: `Failure: ${run.failure_category}` }));
      if (run.answer) content.append(h("section", null, h("h2", { text: "Answer" }), h("p", { class: "answer", text: run.answer })));
      if (["queued", "running", "waiting_for_ingestion"].includes(run.status)) {
        content.append(h("button", { class: "btn", type: "button", text: "Refresh", onclick: loadRun }));
      }
      if (run.claims && run.claims.length) {
        content.append(h("section", null, h("h2", { text: "Claims" }), run.claims.map((claim) => {
          const card = h("article", { class: "card stack" }, h("h3", { text: claim.text }),
            h("p", { class: "muted", text: `Support: ${claim.support}` }));
          if (claim.quote) card.append(h("blockquote", { class: "quote", text: claim.quote }));
          for (const evidence of claim.evidence || []) {
            card.append(h("p", { class: "crumbs", text: `${evidence.handle} · ${paperLabel(run.papers, evidence.paper_id)}` }));
          }
          return card;
        })));
      }
    } catch (problem) {
      if (!active) return;
      status.textContent = problem instanceof Error ? problem.message : "Request failed.";
    }
  }

  void loadRun();
}
