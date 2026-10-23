export function h(tag, attrs, ...children) {
  const element = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") element.className = String(value);
      else if (key === "text") element.textContent = String(value);
      else if (key.startsWith("on") && typeof value === "function") {
        element.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (key === "style") element.setAttribute("style", String(value));
      else element.setAttribute(key, value === true ? "" : String(value));
    }
  }
  for (const child of children) add(element, child);
  return element;
}

function add(element, child) {
  if (child === undefined || child === null || child === false) return;
  if (Array.isArray(child)) {
    child.forEach((item) => add(element, item));
  } else if (child instanceof Node) {
    element.appendChild(child);
  } else {
    element.appendChild(document.createTextNode(String(child)));
  }
}

export function fmtSeconds(seconds) {
  const value = Math.round(seconds);
  return value >= 60
    ? `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`
    : `${value} s`;
}

export function fmtMs(milliseconds) {
  return milliseconds >= 1000
    ? `${(milliseconds / 1000).toFixed(milliseconds >= 10000 ? 0 : 1)} s`
    : `${Math.round(milliseconds)} ms`;
}

export function fmtInt(value) {
  return value.toLocaleString("en-US");
}

export function pill(text, tone = "") {
  const allowed = ["", "ok", "warn", "bad", "live"];
  const normalized = allowed.includes(tone) ? tone : "";
  return h("span", { class: `pill${normalized ? ` ${normalized}` : ""}`, text });
}
