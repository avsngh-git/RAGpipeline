export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const storageName = "research-platform-key";
let servingKey = null;
let servingPromise = null;

export function getKey() {
  try {
    return window.sessionStorage.getItem(storageName) || "";
  } catch (_error) {
    return "";
  }
}

export function setKey(value) {
  servingKey = null;
  servingPromise = null;
  try {
    if (value) window.sessionStorage.setItem(storageName, value);
    else window.sessionStorage.removeItem(storageName);
    return true;
  } catch (_error) {
    return false;
  }
}

export async function api(method, path, body) {
  const key = getKey();
  if (!key) throw new ApiError(401, "missing_api_key", "Enter an API key to continue.");
  const headers = { Authorization: `Bearer ${key}`, Accept: "application/json" };
  const options = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch (_error) {
    throw new ApiError(0, "network_error", "Could not reach the API. Check that the service is running and retry.");
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    payload = {};
  }
  if (!response.ok) {
    const detail = payload.error || {};
    throw new ApiError(
      response.status,
      detail.code || "request_failed",
      detail.message || "Request failed.",
    );
  }
  return payload;
}

export async function serving() {
  const key = getKey();
  if (!key) throw new ApiError(401, "missing_api_key", "Enter an API key to continue.");
  if (servingKey !== key || !servingPromise) {
    servingKey = key;
    servingPromise = api("GET", "/v1/serving");
  }
  return servingPromise;
}
