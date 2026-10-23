import { getKey, serving, setKey } from "./api.js";
import { h } from "./dom.js";
import { route, start } from "./router.js";
import { renderKey } from "./view-key.js";
import { renderSearch, resetSearchState } from "./view-search.js";
import { renderPaper } from "./view-paper.js";
import { renderRun } from "./view-run.js";

const who = document.getElementById("who");

function rerender() {
  window.dispatchEvent(new Event("hashchange"));
}

async function updateHeader() {
  const key = getKey();
  who.replaceChildren();
  if (!key) return;
  const disconnect = h("button", {
    class: "btn",
    type: "button",
    text: "Disconnect",
    onclick: () => {
      setKey("");
      resetSearchState();
      who.replaceChildren();
      rerender();
    },
  });
  try {
    const identity = await serving();
    if (getKey() !== key) return;
    const generation = identity.generation === null ? "unknown" : identity.generation;
    who.append(
      h("span", { text: `snapshot ${String(identity.snapshot_id).slice(0, 8)} · generation ${generation}` }),
      disconnect,
    );
  } catch (_error) {
    if (getKey() !== key) return;
    who.append(h("span", { class: "muted", text: "Serving identity unavailable." }), disconnect);
  }
}

window.addEventListener("ui-key-required", (event) => {
  renderKey(event.detail.main, () => {
    void updateHeader();
    rerender();
  });
});

route(/^#\/search$/, (_match, main) => renderSearch(main));
route(/^#\/papers\/(W[0-9]+)$/, (match, main) => renderPaper(match, main));
route(/^#\/runs\/([0-9a-f-]{36})$/i, (match, main) => renderRun(match, main));

void updateHeader();
start();
