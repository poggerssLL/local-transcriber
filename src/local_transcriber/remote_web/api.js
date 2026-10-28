const PREFIX = "/remote/v1";
const UPLOAD = `${PREFIX}/uploads/resumable`;
const HEX_ID = /^[0-9a-f]{32}$/;
const UUID = /^[0-9a-f-]{36}$/i;
export const CHUNK_BYTES = 8 * 1024 * 1024;
export const pause = (ms, signal) => new Promise((resolve, reject) => {
  if (signal?.aborted) { reject(new DOMException("Cancelado", "AbortError")); return; }
  const timer = setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, ms);
  function abort() { clearTimeout(timer); reject(new DOMException("Cancelado", "AbortError")); }
  signal?.addEventListener("abort", abort, { once: true });
});
export class ApiError extends Error {
  constructor(status, detail, retryAfter = 0) { super(detail); this.status = status; this.retryAfter = retryAfter; }
}
function retryAfter(header, fallback) {
  if (!header) return fallback;
  const seconds = Number(header);
  const delay = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(header) - Date.now();
  return Number.isFinite(delay) ? Math.max(fallback, delay) : fallback;
}
export class RemoteApi {
  constructor({ fetcher = fetch, now = () => Date.now(), sleep = pause } = {}) {
    this.fetcher = fetcher; this.now = now; this.sleep = sleep;
    this.nextRead = 0; this.cooldown = 0; this.csrf = null; this.expires = 0; this.maxUpload = 0;
    this.readTail = Promise.resolve();
    this.sessionPending = null;
  }
  async request(path, { method = "GET", headers = {}, body, signal, raw = false, retry = true } = {}) {
    if (!path.startsWith(`${PREFIX}/`) || path.startsWith("//") || path.includes("..")) throw new Error("Rota inválida");
    if (path !== `${PREFIX}/session` && this.expires && this.now() >= this.expires - 60000) {
      await this.session(signal);
    }
    const reading = method === "GET";
    if (reading) {
      const previous = this.readTail;
      let release;
      this.readTail = new Promise((resolve) => { release = resolve; });
      try { await previous; await this.sleep(Math.max(0, this.nextRead - this.now(), this.cooldown - this.now()), signal); this.nextRead = this.now() + 3000; }
      finally { release(); }
    } else await this.sleep(Math.max(0, this.cooldown - this.now()), signal);
    const sent = { ...headers };
    if (this.csrf && (!reading || path.startsWith(`${UPLOAD}/`))) sent["x-csrf-token"] = this.csrf;
    let response;
    try {
      response = await this.fetcher(path, { method, headers: sent, body, signal, mode: "cors", credentials: "same-origin", cache: "no-store", redirect: "error" });
    } catch (error) { if (signal?.aborted) throw error; throw new ApiError(0, "Conexão interrompida"); }
    if (response.redirected) throw new ApiError(0, "Redirecionamento inesperado");
    if (response.status === 429 || response.status === 503) {
      const delay = retryAfter(response.headers.get("Retry-After"), response.status === 429 ? 12000 : 2000);
      this.cooldown = Math.max(this.cooldown, this.now() + delay);
      if (retry) { await this.sleep(delay, signal); return this.request(path, { method, headers, body, signal, raw, retry }); }
      throw new ApiError(response.status, "Servidor temporariamente ocupado", delay);
    }
    if (!response.ok) {
      let detail = `Erro HTTP ${response.status}`;
      try { const json = await response.json(); if (typeof json.detail === "string") detail = json.detail; } catch { /* malformed error */ }
      if (response.status === 403 && retry && ["invalid or expired CSRF token", "invalid or expired session cookie"].includes(detail)) {
        await this.session(signal);
        return this.request(path, { method, headers, body, signal, raw, retry: false });
      }
      throw new ApiError(response.status, detail);
    }
    if (raw) return response;
    try { return await response.json(); } catch { throw new ApiError(0, "Resposta inválida do servidor"); }
  }
  async session(signal) {
    if (this.sessionPending) return this.sessionPending;
    this.sessionPending = (async () => {
      const data = await this.request(`${PREFIX}/session`, { signal });
      if (typeof data.csrf_token !== "string" || data.csrf_token.length < 32) throw new Error("Sessão inválida");
      if (!Number.isSafeInteger(data.max_upload_bytes) || data.max_upload_bytes <= 0) throw new Error("Limite inválido");
      this.csrf = data.csrf_token; this.expires = Number(data.expires_at) * 1000; this.maxUpload = data.max_upload_bytes;
      return data;
    })();
    try { return await this.sessionPending; } finally { this.sessionPending = null; }
  }
  subjects(signal) { return this.request(`${PREFIX}/subjects`, { signal }); }
  init(intent, signal) { const body = { filename: intent.filename, total_bytes: intent.total_bytes, enqueue: true, subject_id: intent.subject_id }; if (intent.title) body.title = intent.title; if (intent.lesson_date) body.lesson_date = intent.lesson_date; return this.request(UPLOAD, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": intent.init_key, "X-Expected-Sha256": intent.expected_sha256 }, body: JSON.stringify(body), signal, retry: false }); }
  status(id, signal) { if (!HEX_ID.test(id)) throw new Error("ID inválido"); return this.request(`${UPLOAD}/${id}`, { signal }); }
  async patch(id, offset, buffer, hash, signal) {
    if (!HEX_ID.test(id)) throw new Error("ID inválido");
    const response = await this.request(`${UPLOAD}/${id}`, { method: "PATCH", headers: { "Content-Type": "application/octet-stream", "Upload-Offset": String(offset), "X-Chunk-Sha256": hash }, body: buffer, signal, raw: true, retry: false });
    if (response.status !== 204) throw new Error("Resposta PATCH inesperada");
    const confirmed = Number(response.headers.get("Current-Offset"));
    if (confirmed !== offset + buffer.byteLength) throw new Error("Offset confirmado divergente");
    return confirmed;
  }
  finalize(intent, signal) { return this.request(`${UPLOAD}/${intent.upload_id}/finalize`, { method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Sha256": intent.expected_sha256 }, body: "{}", signal, retry: false }); }
  job(id, signal) { if (!UUID.test(id)) throw new Error("Job inválido"); return this.request(`${PREFIX}/jobs/${id}`, { signal }); }
  transcript(id, signal) { if (!UUID.test(id)) throw new Error("Job inválido"); return this.request(`${PREFIX}/jobs/${id}/transcript`, { signal }); }
}
