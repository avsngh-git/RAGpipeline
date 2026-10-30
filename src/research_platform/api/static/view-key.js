import { serving, setKey } from "./api.js";
import { h } from "./dom.js";

export function renderKey(main, onSaved) {
  const form = h("form", { class: "stack" });
  const input = h("input", {
    id: "api-key",
    type: "password",
    autocomplete: "off",
    required: true,
  });
  const error = h("p", { class: "muted", role: "status", "aria-live": "polite" });
  form.append(
    h("label", { for: "api-key", text: "Bearer API key" }),
    input,
    h("button", { class: "btn primary", type: "submit", text: "Connect" }),
    error,
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = input.value.trim();
    if (!setKey(value)) {
      error.textContent = "storage_unavailable: This tab cannot store the key. Enable session storage and try again.";
      return;
    }
    try {
      await serving();
      onSaved();
    } catch (problem) {
      const code = problem && "code" in problem ? problem.code : "request_failed";
      const message = problem instanceof Error ? problem.message : "Request failed.";
      error.textContent = `${code}: ${message}`;
    }
  });
  main.append(
    h("section", { class: "doc" },
      h("h1", { text: "Connect with an API key" }),
      form,
      h("p", { class: "muted" }, "The key stays in this browser tab only. Create one with ",
        h("code", { text: "research-keys create" }), ", or use the key ",
        h("code", { text: "scripts/demo_load.sh" }), " saved in demo-data/api-key."),
    ),
  );
}
