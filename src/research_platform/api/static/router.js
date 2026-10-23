import { getKey } from "./api.js";
import { h } from "./dom.js";

const routes = [];
let cleanups = [];

export function route(pattern, render) {
  routes.push({ pattern, render });
}

export function onLeave(cleanup) {
  cleanups.push(cleanup);
}

function clearView() {
  for (const cleanup of cleanups) cleanup();
  cleanups = [];
  const main = document.getElementById("view");
  main.replaceChildren();
  return main;
}

function focusHeading(main) {
  const heading = main.querySelector("h1");
  if (!heading) return;
  heading.setAttribute("tabindex", "-1");
  heading.focus();
}

function currentRouteName(hash) {
  const segment = hash.replace(/^#\/?/, "").split("/")[0];
  return segment || "search";
}

function render() {
  const hash = window.location.hash;
  const legacy = hash.match(/^#run=([0-9a-f-]{36})$/i);
  if (legacy) {
    window.location.replace(`#/runs/${legacy[1]}`);
    return;
  }
  if (!hash) {
    window.location.hash = "#/search";
    return;
  }

  const main = clearView();
  const nav = document.getElementById("nav");
  const name = currentRouteName(hash);
  nav.querySelectorAll("[data-route]").forEach((link) => {
    if (link.dataset.route === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });

  if (!getKey()) {
    window.dispatchEvent(new CustomEvent("ui-key-required", { detail: { main } }));
    focusHeading(main);
    return;
  }

  for (const item of routes) {
    const match = hash.match(item.pattern);
    if (match) {
      item.render(match, main);
      focusHeading(main);
      return;
    }
  }
  main.appendChild(h("h1", { text: "Page not found" }));
  main.appendChild(h("p", null, h("a", { href: "#/search", text: "Return to search" })));
  focusHeading(main);
}

export function start() {
  window.addEventListener("hashchange", render);
  render();
}
