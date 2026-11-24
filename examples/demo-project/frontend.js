// Small browser helpers: debounce, API client, and a polling subscriber.

export function debounce(fn, wait = 300) {
  let timer = null;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), wait);
  };
}

export class ApiClient {
  constructor(baseUrl, { timeout = 8000, retries = 2 } = {}) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.timeout = timeout;
    this.retries = retries;
  }

  async request(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    let lastError;
    for (let attempt = 0; attempt <= this.retries; attempt++) {
      try {
        const resp = await fetch(this.baseUrl + path, {
          ...options,
          signal: controller.signal,
          headers: { "Content-Type": "application/json", ...options.headers },
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
      } catch (err) {
        lastError = err;
        if (err.name === "AbortError") break;
        await new Promise((r) => setTimeout(r, 2 ** attempt * 200));
      }
    }
    clearTimeout(timer);
    throw lastError;
  }

  get(path) {
    return this.request(path);
  }

  post(path, body) {
    return this.request(path, { method: "POST", body: JSON.stringify(body) });
  }
}

export function poll(fn, interval, shouldStop) {
  let stopped = false;
  async function tick() {
    while (!stopped && !shouldStop()) {
      try {
        await fn();
      } catch (err) {
        console.warn("poll iteration failed", err);
      }
      await new Promise((r) => setTimeout(r, interval));
    }
  }
  tick();
  return () => { stopped = true; };
}
