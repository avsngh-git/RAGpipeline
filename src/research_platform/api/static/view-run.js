import { ApiError, api } from "./api.js";
import { h, pill } from "./dom.js";
import { onLeave } from "./router.js";
import { failureLine, fetchModelText, renderStory, statusPill } from "./run-record.js";

const ACTIVE = ["queued", "running", "waiting_for_ingestion"];
const viewState = new Map();
const citationPattern = /\[([A-Za-z][A-Za-z0-9]*(?:,\s*[A-Za-z][A-Za-z0-9]*)*)\]/g;
const CHECK_REASONS = {
  quote_found: "the quote was not found in the cited passage",
  words_from_quote: "fewer than half of the claim's content words come from its quote",
  numbers_from_quote: "the claim has a number its quote does not",
  intensifiers_from_quote: "the claim uses a scope word (such as both, all, best) its quote does not",
  no_handles_in_text: "the claim text contains an evidence handle",
  quote_names_its_row: "the table quote does not name its row",
  no_other_row_named: "the claim names a different table row",
};
const DIAGNOSIS_LABELS = {
  drafts_rejected: "Drafted claims by verdict",
  planner_never_discovered: "The planner never chose discover_papers; tools it used",
  tool_rejections: "Rejected tool calls",
  llm_repairs: "Model output repairs",
  model_declared_insufficient: "The model said the evidence was insufficient",
  no_evidence_collected: "No evidence was collected",
  omitted_evidence: "Evidence left out of synthesis",
  ingestion_wait_cap: "Ingestion wait limit reached",
  cancelled_by_principal: "Cancelled by its owner",
};

function checkReason(name) {
  return CHECK_REASONS[name] || name.replaceAll("_", " ");
}

function diagnosisLabel(code) {
  if (code.startsWith("failed_check:")) {
    return `Failed check: ${checkReason(code.slice("failed_check:".length))}`;
  }
  return DIAGNOSIS_LABELS[code] || code.replaceAll("_", " ").replaceAll(":", ": ");
}

function clock(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function localTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

function paperLabel(papers, paperId) {
  const paper = (papers || []).find((item) => item.paper_id === paperId);
  if (!paper) return paperId || "Unknown paper";
  return [paper.title || paper.paper_id, paper.publication_year]
    .filter((part) => part !== null && part !== undefined)
    .join(" · ");
}

function claimForHandle(claims) {
  const result = new Map();
  (claims || []).forEach((claim, index) => {
    for (const evidence of claim.evidence || []) {
      if (!result.has(evidence.handle)) result.set(evidence.handle, index + 1);
    }
  });
  return result;
}

function renderAnswer(answer, claims, state) {
  if (!answer) return h("p", { class: "muted", text: "The agent is still gathering evidence. The answer appears here when synthesis and verification finish." });
  const sourceClaims = claimForHandle(claims);
  const output = h("p", { class: "answer" });
  let offset = 0;
  citationPattern.lastIndex = 0;
  for (const match of answer.matchAll(citationPattern)) {
    const before = answer.slice(offset, match.index);
    const handles = match[1].split(",").map((handle) => handle.trim()).filter((handle) => sourceClaims.has(handle));
    if (handles.length) {
      output.append(document.createTextNode(before.replace(/\s+$/, "")));
      for (const handle of handles) {
        const claimNumber = sourceClaims.get(handle);
        output.append(h("sup", null, h("button", {
          class: "citation-link",
          type: "button",
          title: `Go to claim ${claimNumber} (${handle})`,
          text: String(claimNumber),
          onclick: () => {
            const target = document.getElementById(`claim-${claimNumber}`);
            if (!target) return;
            target.scrollIntoView({ behavior: "smooth", block: "center" });
            target.classList.add("flash");
            window.setTimeout(() => target.classList.remove("flash"), 1400);
          },
        })));
      }
    } else {
      output.append(document.createTextNode(before));
    }
    offset = match.index + match[0].length;
  }
  output.append(document.createTextNode(answer.slice(offset)));
  return output;
}

function renderClaims(claims, papers) {
  if (!claims || !claims.length) return null;
  const items = claims.map((claim, index) => h("li", { id: `claim-${index + 1}`, class: "claim" },
    h("p", { class: "claim-text", text: claim.text }),
    claim.quote ? h("blockquote", { class: "quote" }, h("mark", { text: claim.quote })) : null,
    (claim.evidence || []).map((evidence) => h("p", { class: "crumbs" },
      h("a", { href: `#/papers/${encodeURIComponent(evidence.paper_id)}`, text: paperLabel(papers, evidence.paper_id) }),
      ` · ${evidence.handle}`)),
    claim.support && claim.support !== "supported" ? pill(claim.support.replaceAll("_", " "), "warn") : null));
  return h("section", null, h("h2", { text: "Claims and their sources" }), h("ol", { class: "notes" }, items));
}

function renderDrafts(drafts) {
  if (!drafts || !drafts.length) return null;
  const removed = drafts.filter((draft) => draft.verdict !== "kept");
  const kept = drafts.filter((draft) => draft.verdict === "kept" || draft.verdict === "kept_as_quote").length;
  if (!removed.length) {
    return h("section", null, h("h2", { text: "What verification removed" }),
      h("p", { class: "muted", text: "Verification kept every drafted claim." }));
  }
  const items = removed.map((draft) => {
    const replaced = draft.verdict === "kept_as_quote";
    let reason = "";
    if (draft.verdict === "unknown_handle") reason = "It cited a handle that was never shown to the model.";
    else if (draft.verdict === "not_shown") reason = "It cited a passage the model did not see.";
    else if (draft.verdict === "failed_checks") reason = `It failed quote verification: ${(draft.failed_checks || []).map(checkReason).join("; ")}.`;
    else if (replaced) reason = "It failed its checks, so its verified quote is shown as the claim instead.";
    return h("li", { class: "dropped" },
      h("div", { class: "row" }, pill(draft.verdict.replaceAll("_", " "), replaced ? "warn" : "bad"), h("span", { class: "mono", text: draft.handle })),
      replaced ? h("p", { class: "text-reading", text: draft.text }) : h("p", { class: "text-reading" }, h("del", { text: draft.text })),
      h("p", { class: "muted", text: reason }));
  });
  return h("section", null, h("h2", { text: "What verification removed" }),
    h("p", { class: "muted", text: `The model drafted ${drafts.length} claims. Code kept ${kept} and removed or changed these:` }),
    h("ul", { class: "dropped-list" }, items));
}

function meter(label, value, maximum, formatter = (item) => String(item)) {
  const current = Math.max(0, Number(value) || 0);
  const limit = Math.max(0, Number(maximum) || 0);
  const width = limit ? Math.min(100, (current / limit) * 100) : 0;
  return h("div", { class: "meter" },
    h("span", { text: label }),
    h("meter", { min: "0", max: String(limit || 1), value: String(Math.min(current, limit || 1)), "aria-label": label, class: width >= 85 ? "hot" : "" }),
    h("span", { class: "num", text: `${formatter(current)} / ${formatter(limit)}` }));
}

function provenanceRows(run, identity) {
  const source = run.provenance;
  if (!source) return h("p", { class: "muted", text: "Provenance is recorded when the run starts." });
  const model = source.model || {};
  const rows = [
    ["Run ID", run.run_id],
    ["Configuration", source.configuration_id],
    ["Model", [model.name, model.quantization, [model.runtime, model.runtime_version].filter(Boolean).join(" ")].filter(Boolean).join(" · ")],
    ["Prompts", Object.entries(source.prompt_versions || {}).map(([name, version]) => `${name}: ${version}`).join(" · ") || "—"],
    ["Retrieval profile", source.retrieval_profile_id],
    ["Snapshot and generation", `${source.snapshot_id || "—"}${source.generation ? ` · generation ${source.generation}` : ""}`],
    ["Code revision", source.code_revision],
  ];
  const reranker = source.reranker_runtime;
  if (reranker) rows.push(["Reranker", `${reranker.device} · ${reranker.precision}`]);
  rows.push(["Trace", source.trace_id]);
  const traceUrl = identity?.langfuse_ui_url && source.trace_id
    ? `${identity.langfuse_ui_url.replace(/\/$/, "")}/${encodeURIComponent(source.trace_id)}` : null;
  return h("dl", { class: "kv" }, rows.flatMap(([label, value]) => [
    h("dt", { text: label }), h("dd", { class: label === "Run ID" || label === "Configuration" || label === "Trace" ? "mono" : "", text: value || "—" }),
  ]).concat(traceUrl ? [
    h("dt", { text: "Trace viewer" }),
    h("dd", null, h("a", { href: traceUrl, rel: "noreferrer", target: "_blank", text: "Open trace in Langfuse" })),
  ] : []));
}

function renderBudgets(run, record, identity) {
  const usage = run.usage || {};
  const budgets = run.provenance?.budgets;
  return h("section", null, h("h2", { text: "Budgets and provenance" }),
    budgets ? h("div", { class: "budget-list" },
      meter("Plan rounds", usage.plan_rounds, budgets.max_plan_rounds),
      meter("Tool calls", usage.tool_calls, budgets.max_tool_calls),
      meter("Active time", usage.active_seconds, budgets.max_active_seconds, clock),
      meter("Evidence passages", record?.diagnosis?.evidence_count, budgets.max_evidence_passages),
      h("p", { class: "muted", text: `Model calls: ${usage.model_calls || 0}` }))
      : h("p", { class: "muted", text: "Provenance is recorded when the run starts." }),
    provenanceRows(run, identity));
}

function renderIngestion(run) {
  const parts = [];
  if (run.status === "waiting_for_ingestion") parts.push(h("p", { class: "notice", text: "Waiting for proposed papers to be ingested." }));
  if (run.uningested_candidates?.length) {
    parts.push(h("div", { class: "notice stack" },
      h("p", { text: "Papers the agent proposed but could not ingest:" }),
      h("ul", null, run.uningested_candidates.map((paper) => h("li", { text: paperLabel([paper], paper.paper_id) })))));
  }
  return parts;
}

export function renderRun(match, main) {
  const runId = match[1];
  let state = viewState.get(runId);
  if (!state) {
    state = { textCache: new Map(), openSet: new Set(), identity: null, polling: null, cancelled: false };
    viewState.set(runId, state);
  }
  let active = true;
  let timer = null;
  let previousActive = false;
  onLeave(() => {
    active = false;
    if (timer !== null) window.clearTimeout(timer);
  });
  const status = h("p", { class: "muted", role: "status", "aria-live": "polite", text: "Loading run…" });
  const content = h("div", { class: "stack run-content" });
  main.append(h("section", { class: "doc stack" }, status, content));

  function showError(problem) {
    status.hidden = false;
    const message = problem instanceof ApiError && problem.status === 404
      ? "This run does not exist, or it belongs to another key."
      : problem instanceof Error ? problem.message : "Could not load this run.";
    status.textContent = message;
  }

  async function cancelRun() {
    state.cancelled = true;
    state.confirmCancel = false;
    if (timer !== null) window.clearTimeout(timer);
    try {
      await api("POST", `/v1/research/${runId}/cancel`);
      if (active) await load();
    } catch (problem) {
      if (!active) return;
      if (problem instanceof ApiError && problem.status === 409) await load();
      else status.textContent = problem instanceof Error ? problem.message : "Could not cancel the run.";
    } finally {
      state.cancelled = false;
    }
  }

  function schedulePoll() {
    timer = window.setTimeout(() => {
      if (!active) return;
      if (document.hidden) schedulePoll();
      else void load();
    }, 3000);
  }

  async function load() {
    if (!active) return;
    const scroll = window.scrollY;
    try {
      const [run, record] = await Promise.all([
        api("GET", `/v1/research/${runId}`),
        api("GET", `/v1/research/${runId}/record`),
      ]);
      if (!active) return;
      const wasActive = previousActive;
      const isActive = ACTIVE.includes(run.status);
      if (wasActive && !isActive) {
        const [finalRun, finalRecord] = await Promise.all([
          api("GET", `/v1/research/${runId}`),
          api("GET", `/v1/research/${runId}/record`),
        ]);
        if (!active) return;
        draw(finalRun, finalRecord, scroll);
        previousActive = false;
        return;
      }
      draw(run, record, scroll);
      previousActive = isActive;
      if (isActive && !state.cancelled) schedulePoll();
    } catch (problem) {
      if (active) showError(problem);
    }
  }

  function draw(run, record, scroll) {
    status.hidden = true;
    const modeLabel = run.mode === "deep_research" ? "deep research" : "quick";
    const active = ACTIVE.includes(run.status);
    const header = h("div", { class: "run-header stack" },
      h("p", { class: "eyebrow", text: `Research run · ${modeLabel} · ${localTime(run.created_at)}` }),
      h("h1", { class: "run-question", text: run.question }),
      h("div", { class: "row" }, statusPill(run),
      h("span", { class: "muted", text: `${(run.claims || []).length} verified claims · ${clock(run.usage?.active_seconds || 0)} · ${run.usage?.tool_calls || 0} tool calls` })),
      active ? (state.cancelled ? h("p", { class: "muted", text: "Cancelling run…" }) : state.confirmCancel
        ? h("div", { class: "row cancel-confirm" },
          h("span", { text: "Stop this run? It keeps what it has recorded." }),
          h("button", { class: "btn danger", type: "button", text: "Cancel run", onclick: () => { void cancelRun(); } }),
          h("button", { class: "btn", type: "button", text: "Keep running", onclick: () => { state.confirmCancel = false; draw(run, record, window.scrollY); } }))
        : h("button", { class: "btn danger", type: "button", text: "Cancel run", onclick: () => { state.confirmCancel = true; draw(run, record, window.scrollY); } })) : null);
    const parts = [header, ...renderIngestion(run),
      h("section", null, h("h2", { text: "Answer" }),
        run.answer ? renderAnswer(run.answer, run.claims, state) : run.status === "failed"
          ? h("p", { class: "muted" }, "This run stopped before it wrote an answer. ", failureLine(run.failure_category))
          : renderAnswer(null, run.claims, state)),
      renderClaims(run.claims, run.papers),
      h("section", null, h("h2", { text: "How this answer was made" }), renderStory(run, record, state.textCache, state.openSet, (ordinal) => fetchModelText(runId, ordinal))),
      renderDrafts(record.drafted_claims),
      h("section", null, h("h2", { text: "Diagnosis" }),
        h("p", { text: record.diagnosis.stage === "none" ? "No problem found." : record.diagnosis.stage === "in_progress" ? "The run is still in progress." : `Attributed to the ${record.diagnosis.stage} stage.` }),
        (record.diagnosis.findings || []).map((finding) => h("p", null,
          h("span", { text: diagnosisLabel(finding.code) + (finding.detail ? ":" : "") }), " ", h("span", { class: "mono muted", text: finding.detail })))),
      renderBudgets(run, record, state.identity)];
    content.replaceChildren(...parts.filter(Boolean));
    for (const details of content.querySelectorAll("details")) {
      const key = details.querySelector("summary")?.textContent;
      if (key === "Prompt, thinking and output") details.open = state.openSet.has(`model:${details.dataset.ordinal}`);
    }
    window.scrollTo(0, scroll);
  }

  void api("GET", "/v1/me").then((identity) => {
    state.identity = identity;
    if (active) void load();
  }).catch(() => { if (active) void load(); });
}
