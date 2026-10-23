import { api } from "./api.js";
import { fmtMs, h, pill } from "./dom.js";

const activeStatuses = ["queued", "running", "waiting_for_ingestion"];

function clock(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function statusPill(view) {
  if (view.status === "queued") return pill("queued", "live");
  if (view.status === "running") return pill(`running · ${clock(view.usage?.active_seconds ?? view.active_seconds ?? 0)}`, "live");
  if (view.status === "waiting_for_ingestion") return pill("waiting for ingestion", "live");
  if (view.status === "failed") {
    const category = view.failure_category === "cancelled_by_principal" ? "cancelled" : `failed · ${view.failure_category || "unknown"}`;
    return pill(category, view.failure_category === "cancelled_by_principal" ? "warn" : "bad");
  }
  const outcome = String(view.answer_outcome || "completed").replaceAll("_", " ");
  return pill(outcome, outcome === "answered" ? "ok" : "warn");
}

export function failureLine(category) {
  const lines = {
    model_unavailable: "The local model could not be reached.",
    invalid_model_output: "The model returned an answer the system could not verify.",
    budget_exhausted: "It reached a research budget limit.",
    timeout: "It ran out of its time budget.",
    retrieval_error: "A retrieval step failed.",
    resume_exhausted: "It could not resume within its retry budget.",
    configuration_changed: "The run's configuration changed while it was active.",
    internal: "The run stopped because of an internal error.",
    cancelled_by_principal: "You cancelled this run.",
  };
  return lines[category] || "The run stopped before it finished.";
}

export function storyEvents(record) {
  const events = [
    ...(record.tool_calls || []).map((call) => ({ ...call, event_type: "tool" })),
    ...(record.model_calls || []).map((call) => ({ ...call, event_type: "model" })),
  ];
  return events.sort((left, right) => {
    const leftTime = left.recorded_at ? Date.parse(left.recorded_at) : Number.POSITIVE_INFINITY;
    const rightTime = right.recorded_at ? Date.parse(right.recorded_at) : Number.POSITIVE_INFINITY;
    return leftTime - rightTime || left.ordinal - right.ordinal;
  });
}

function modelText(text) {
  if (!text) return null;
  return h("pre", { class: "textblock", text });
}

function renderModelPayload(parent, value) {
  parent.replaceChildren();
  if (value.state === "not_recorded") {
    parent.append(h("p", { class: "muted", text: "Model text was not recorded for this call (trace content level below full)." }));
  } else if (value.state === "withheld") {
    parent.append(h("p", { class: "muted", text: "Model text is withheld: this server does not serve source-linked evidence." }));
  } else {
    for (const message of value.messages || []) {
      parent.append(h("p", { class: "role", text: message.role }), modelText(message.content));
    }
    if (value.thinking) parent.append(h("p", { class: "role", text: "Thinking" }), modelText(value.thinking));
    if (value.output) parent.append(h("p", { class: "role", text: "Output" }), modelText(value.output));
    if (value.error_preview) parent.append(h("p", { class: "role", text: "Error" }), modelText(value.error_preview));
  }
}

function formatSummary(summary) {
  return Object.entries(summary || {}).map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`).join(" · ");
}

export function renderStory(view, record, textCache, openSet, fetchText) {
  const list = h("ol", { class: "story" });
  const events = storyEvents(record);
  for (const event of events) {
    const key = `${event.event_type}:${event.ordinal}`;
    const isModel = event.event_type === "model";
    const failed = event.status === "failed" || event.status === "rejected";
    const item = h("li", { class: [isModel ? "model" : "tool", failed ? "fail" : ""].filter(Boolean).join(" ") });
    const title = isModel
      ? ({ plan: "Planned the next searches", evaluate: "Judged whether the evidence was enough", synthesize: "Wrote the answer", judge: "Checked claim support", probe: "Checked the model" }[event.kind] || `Model call · ${event.kind}`)
      : "Tool call";
    item.append(h("div", { class: "spread" },
      h("strong", { text: title }), h("span", { class: "muted num", text: fmtMs(event.duration_ms || 0) })));
    if (isModel) {
      const meta = [event.model_name,
        event.prompt_tokens === null || event.prompt_tokens === undefined ? null : `${event.prompt_tokens} in`,
        event.output_tokens === null || event.output_tokens === undefined ? null : `${event.output_tokens} out`,
        event.thinking_chars === null || event.thinking_chars === undefined ? null : `thinking ${event.thinking_chars} characters`,
        event.attempts > 1 ? `${event.attempts} attempts` : null].filter(Boolean).join(" · ");
      if (meta) item.append(h("p", { class: "muted crumbs", text: meta }));
      const details = h("details", { open: openSet.has(key) }, h("summary", { text: "Prompt, thinking and output" }));
      details.dataset.ordinal = String(event.ordinal);
      const body = h("div", { class: "stack model-payload" });
      if (!event.text_recorded) renderModelPayload(body, { state: "not_recorded" });
      else if (textCache.has(key)) renderModelPayload(body, textCache.get(key));
      else if (openSet.has(key)) void loadText();
      details.append(body);
      details.addEventListener("toggle", () => {
        if (details.open) {
          openSet.add(key);
          if (event.text_recorded && !textCache.has(key)) void loadText();
        } else openSet.delete(key);
      });
      async function loadText() {
        body.replaceChildren(h("p", { class: "muted", text: "Loading model text…" }));
        try {
          const value = await fetchText(event.ordinal);
          textCache.set(key, value);
          renderModelPayload(body, value);
        } catch (problem) {
          body.replaceChildren(h("p", { class: "muted", text: problem instanceof Error ? problem.message : "Could not load model text." }));
        }
      }
      item.append(details);
    } else {
      item.append(h("p", { class: "mono", text: `Called ${event.tool_name}` }));
      item.append(h("code", { class: "textblock", text: JSON.stringify(event.arguments || {}) }));
      const summary = formatSummary(event.result_summary);
      if (summary) item.append(h("p", { class: "crumbs muted", text: summary }));
      if (event.status !== "succeeded") item.append(pill(
        event.status === "cached" ? "cached" : `${event.status}${event.error_category ? ` · ${event.error_category}` : ""}`,
        event.status === "cached" ? "" : failed ? "bad" : "warn"));
    }
    list.append(item);
  }
  if (activeStatuses.includes(view.status)) {
    const last = events.map((event) => event.recorded_at).filter(Boolean).at(-1) || view.created_at;
    const elapsed = last ? Math.max(0, Math.floor((Date.now() - Date.parse(last)) / 1000)) : 0;
    list.append(h("li", { class: "pending", text: `Working · ${clock(elapsed)} since the last step` }));
  }
  return list;
}

export function fetchModelText(runId, ordinal) {
  return api("GET", `/v1/research/${runId}/model-calls/${ordinal}`);
}
