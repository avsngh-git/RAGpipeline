import { ApiError, api } from "./api.js";
import { h } from "./dom.js";
import { onLeave } from "./router.js";

const availabilityMessages = {
  no_research_scope:
    "This key can search and read runs but cannot start them, because it lacks the research scope. Starting a run also needs the local model on a machine with an NVIDIA GPU (the stack's llm profile). With Docker Compose, create a key with docker compose run --rm --no-deps api research-keys create --principal <name> --scope read --scope research.",
  service_unavailable: "The research service is not running on this server.",
  model_unreachable:
    "Research runs need the local model. This server cannot reach Ollama, so a run would fail. Search, paper pages and saved runs still work. To run research, start the stack with the llm profile on a machine with an NVIDIA GPU (see the README).",
};

export function renderNewRun(main) {
  let active = true;
  onLeave(() => { active = false; });
  const notice = h("div", { class: "notice", role: "status", text: "Checking research availability…" });
  const error = h("p", { class: "notice", role: "alert", hidden: true });
  const question = h("textarea", {
    id: "run-question",
    rows: "5",
    required: true,
    minlength: "3",
    maxlength: "2000",
    "aria-describedby": "question-hint",
  });
  const modeQuick = h("input", { id: "mode-quick", type: "radio", name: "mode", value: "quick" });
  const modeDeep = h("input", { id: "mode-deep", type: "radio", name: "mode", value: "deep_research", checked: true });
  const yearFrom = h("input", { id: "run-year-from", type: "number", min: "1900", max: "2100", step: "1" });
  const yearTo = h("input", { id: "run-year-to", type: "number", min: "1900", max: "2100", step: "1" });
  const submit = h("button", { id: "start-run", class: "btn primary", type: "submit", disabled: true, text: "Start run" });
  const form = h("form", { class: "stack" },
    h("div", { class: "field" },
      h("label", { for: "run-question", text: "Research question" }),
      question,
      h("p", { id: "question-hint", class: "muted", text: "3–2000 characters after trimming." })),
    h("fieldset", { class: "field mode-options" },
      h("legend", { text: "Research mode" }),
      h("label", null, modeQuick, " Quick — A fixed search sequence, then one answer. About 3–4 minutes on an RTX 3050."),
      h("label", null, modeDeep, " Deep research — The model plans rounds of searches and decides when the evidence is enough. Usually 5–8 minutes; it stops at 30.")),
    h("div", { class: "formgrid" },
      h("div", { class: "field" }, h("label", { for: "run-year-from", text: "Published from" }), yearFrom),
      h("div", { class: "field" }, h("label", { for: "run-year-to", text: "to" }), yearTo)),
    error,
    h("div", { class: "row" }, submit));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!active) return;
    const text = question.value.trim();
    error.hidden = true;
    if (text.length < 3 || text.length > 2000) {
      error.textContent = "Enter a question between 3 and 2000 characters after trimming.";
      error.hidden = false;
      return;
    }
    if (yearFrom.value && yearTo.value && Number(yearFrom.value) > Number(yearTo.value)) {
      error.textContent = "The start year must be no later than the end year.";
      error.hidden = false;
      return;
    }
    submit.disabled = true;
    submit.textContent = "Starting…";
    try {
      const filters = {};
      if (yearFrom.value) filters.year_from = Number(yearFrom.value);
      if (yearTo.value) filters.year_to = Number(yearTo.value);
      const run = await api("POST", "/v1/research", {
        question: text,
        mode: modeQuick.checked ? "quick" : "deep_research",
        filters,
      });
      if (active) window.location.hash = `#/runs/${run.run_id}`;
    } catch (problem) {
      if (!active) return;
      const message = problem instanceof ApiError && problem.status === 429 && problem.code === "too_many_active_runs"
        ? "You already have the maximum number of active runs. Wait for one to finish or cancel it."
        : `${problem instanceof ApiError ? problem.code : "request_failed"}: ${problem instanceof Error ? problem.message : "Request failed."}`;
      error.textContent = message;
      error.hidden = false;
      submit.disabled = false;
      submit.textContent = "Start run";
    }
  });

  main.append(h("section", { class: "doc stack" }, h("h1", { text: "Start a research run" }), notice, form));
  void api("GET", "/v1/me").then((identity) => {
    if (!active) return;
    const state = identity.research_runs;
    if (state === "available") {
      notice.hidden = true;
      submit.disabled = false;
    } else {
      notice.textContent = availabilityMessages[state] || "Research runs are not available on this server.";
      submit.disabled = true;
    }
  }).catch((problem) => {
    if (!active) return;
    notice.textContent = problem instanceof Error ? problem.message : "Research availability could not be checked.";
    submit.disabled = true;
  });
}
