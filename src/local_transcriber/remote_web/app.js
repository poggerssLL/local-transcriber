import { RemoteApi, ApiError, CHUNK_BYTES, pause } from "./api.js";
import { byId, message, activity, bytes, renderSubjects, renderTranscript } from "./dom.js";

const K = new Uint32Array([
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
]);
const rotate = (x, n) => (x >>> n) | (x << (32 - n));
export const hex = (buffer) => Array.from(new Uint8Array(buffer), (x) => x.toString(16).padStart(2, "0")).join("");
export class Sha256 {
  constructor() {
    this.h = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
    this.tail = new Uint8Array(64); this.used = 0; this.length = 0; this.done = false;
  }
  block(data, start) {
    const w = new Uint32Array(64);
    for (let i = 0; i < 16; i++) { const p = start + 4 * i; w[i] = ((data[p] << 24) | (data[p+1] << 16) | (data[p+2] << 8) | data[p+3]) >>> 0; }
    for (let i = 16; i < 64; i++) { const a = w[i-15], b = w[i-2]; w[i] = (w[i-16] + (rotate(a,7) ^ rotate(a,18) ^ (a >>> 3)) + w[i-7] + (rotate(b,17) ^ rotate(b,19) ^ (b >>> 10))) >>> 0; }
    let [a,b,c,d,e,f,g,h] = this.h;
    for (let i = 0; i < 64; i++) { const t1 = (h + (rotate(e,6)^rotate(e,11)^rotate(e,25)) + ((e&f)^(~e&g)) + K[i] + w[i]) >>> 0; const t2 = ((rotate(a,2)^rotate(a,13)^rotate(a,22)) + ((a&b)^(a&c)^(b&c))) >>> 0; h=g; g=f; f=e; e=(d+t1)>>>0; d=c; c=b; b=a; a=(t1+t2)>>>0; }
    for (const [i, value] of [a,b,c,d,e,f,g,h].entries()) this.h[i] = (this.h[i] + value) >>> 0;
  }
  update(bytesIn) {
    if (this.done) throw new Error("Hash finalizado");
    const data = bytesIn instanceof Uint8Array ? bytesIn : new Uint8Array(bytesIn);
    this.length += data.length;
    if (!Number.isSafeInteger(this.length)) throw new Error("Arquivo grande demais");
    let p = 0;
    if (this.used) { const take = Math.min(64-this.used, data.length); this.tail.set(data.subarray(0,take),this.used); this.used += take; p += take; if (this.used === 64) { this.block(this.tail,0); this.used = 0; } }
    while (p + 64 <= data.length) { this.block(data,p); p += 64; }
    if (p < data.length) { this.tail.set(data.subarray(p),0); this.used = data.length-p; }
    return this;
  }
  digest() {
    if (this.done) throw new Error("Hash finalizado");
    const length = this.length; this.tail[this.used++] = 0x80;
    if (this.used > 56) { this.tail.fill(0,this.used); this.block(this.tail,0); this.used = 0; }
    this.tail.fill(0,this.used,56);
    const high = Math.floor(length / 0x20000000), low = (length * 8) >>> 0;
    for (let i = 0; i < 4; i++) { this.tail[56+i] = (high >>> (24-8*i)) & 255; this.tail[60+i] = (low >>> (24-8*i)) & 255; }
    this.block(this.tail,0); this.done = true;
    return Array.from(this.h, (word) => word.toString(16).padStart(8,"0")).join("");
  }
}
export async function hashFile(file, { signal, progress = () => {}, chunkBytes = CHUNK_BYTES } = {}) {
  if (!globalThis.crypto?.subtle) throw new Error("HTTPS e Web Crypto são necessários para enviar áudio");
  const sha = new Sha256(), chunks = new Map();
  for (let offset = 0; offset < file.size; offset += chunkBytes) {
    if (signal?.aborted) throw new DOMException("Cancelado", "AbortError");
    const end = Math.min(file.size, offset+chunkBytes);
    const buffer = await file.slice(offset,end).arrayBuffer();
    sha.update(new Uint8Array(buffer));
    chunks.set(offset, { length: buffer.byteLength, hash: hex(await crypto.subtle.digest("SHA-256",buffer)) });
    progress(end,file.size); await pause(0,signal);
  }
  return { total: sha.digest(), chunks };
}

const STORAGE = "lt.remote.pending.v1";
const LEASE = "lt.remote.lease.v1";
const ID = /^[0-9a-f]{32}$/;
const HASH = /^[0-9a-f]{64}$/;
const uid = () => crypto.randomUUID();
function validIntent(x) { return x && x.version === 1 && HASH.test(x.expected_sha256) && typeof x.filename === "string" && Number.isSafeInteger(x.total_bytes) && x.total_bytes > 0 && typeof x.init_key === "string" && (!x.upload_id || ID.test(x.upload_id)); }
function load() { try { const x = JSON.parse(localStorage.getItem(STORAGE)); return validIntent(x) ? x : null; } catch { return null; } }
function save(x) { try { localStorage.setItem(STORAGE,JSON.stringify(x)); return true; } catch { message("Armazenamento local indisponível; mantenha esta aba aberta para recuperar o envio."); return false; } }
function clear() { try { localStorage.removeItem(STORAGE); } catch { /* private browsing */ } }
function filename(file) { const name = file.name.normalize("NFC"); if (!name || name.length > 255 || /[\\/\x00-\x1f]/.test(name) || !/\.(m4a|aac|mp3|wav)$/i.test(name)) throw new Error("Escolha um arquivo M4A, AAC, MP3 ou WAV com nome válido"); return name; }
function verifyStatus(data, intent) {
  if (data.expected_sha256 !== intent.expected_sha256 || data.total_bytes !== intent.total_bytes || !Number.isSafeInteger(data.current_offset) || data.current_offset < 0 || data.current_offset > intent.total_bytes) throw new Error("Manifesto remoto divergente; envio bloqueado");
  if (data.current_offset < intent.total_bytes && data.current_offset % CHUNK_BYTES !== 0) throw new Error("Offset remoto não alinhado; reconciliação necessária");
  return data;
}
export class RemoteController {
  constructor(api = new RemoteApi()) { this.api = api; this.intent = null; this.file = null; this.hashes = null; this.generation = 0; this.controller = null; this.running = false; this.owner = uid(); this.noJobChecks = 0; }
  next() { this.controller?.abort(); this.controller = new AbortController(); this.generation++; return { generation:this.generation, signal:this.controller.signal }; }
  current(t) { return t.generation === this.generation && !t.signal.aborted; }
  setIntent(x,t) { if (this.current(t)) { this.intent = x; save(x); } }
  lease() { try { const old = JSON.parse(localStorage.getItem(LEASE)); if (old && old.owner !== this.owner && old.until > Date.now()) return false; localStorage.setItem(LEASE,JSON.stringify({owner:this.owner,until:Date.now()+15000})); return true; } catch { return true; } }
  releaseLease() { try { const old = JSON.parse(localStorage.getItem(LEASE)); if (old?.owner === this.owner) localStorage.removeItem(LEASE); } catch { /* private browsing */ } }
  async bootstrap() {
    const t = this.next(); message("Conectando ao notebook…");
    await this.api.session(t.signal);
    const subjects = await this.api.subjects(t.signal);
    if (!Array.isArray(subjects)) throw new Error("Lista de matérias inválida");
    if (!this.current(t)) return;
    renderSubjects(subjects);
    for (const id of ["subject","file","title","lesson-date"]) byId(id).disabled = false;
    byId("submit").disabled = subjects.length === 0;
    if (!subjects.length) message("Nenhuma matéria disponível para envio remoto."); else message("Pronto para enviar.");
    this.intent = load();
    if (this.intent) { byId("submit").disabled = true; for (const id of ["subject","title","lesson-date"]) byId(id).disabled = true; activity(`Envio salvo: ${this.intent.raw_filename || this.intent.filename} (${bytes(this.intent.total_bytes)}).`); await this.resume(t); }
  }
  async start(file, subject, title, lessonDate) {
    if (this.intent) throw new Error("Esqueça o acompanhamento atual antes de iniciar outro envio");
    if (!file || file.size <= 0 || file.size > this.api.maxUpload) throw new Error("Tamanho do áudio fora do limite permitido");
    const name = filename(file); if (!subject) throw new Error("Selecione a matéria");
    if (title.length > 500) throw new Error("Título longo demais");
    const t = this.next(); this.file = file; byId("pause").hidden = false; message("Verificando arquivo…");
    this.hashes = await hashFile(file,{ signal:t.signal, progress:(done,total)=>{ if(this.current(t)) activity(`Verificando arquivo: ${Math.round(done*100/total)}%.`); } });
    if (!this.current(t)) return;
    this.setIntent({version:1,upload_id:null,expected_sha256:this.hashes.total,filename:name,raw_filename:file.name,total_bytes:file.size,subject_id:subject,title:title || null,lesson_date:lessonDate || null,job_id:null,recording_id:null,init_key:uid(),confirmed_offset:0,expires_at:null},t);
    await this.drive(t);
  }
  async resume(t = this.next()) {
    if (!this.intent || !this.current(t)) return;
    if (this.intent.job_id) return this.track(t);
    if (this.intent.upload_id) {
      try { const data = verifyStatus(await this.api.status(this.intent.upload_id,t.signal),this.intent); return this.state(data,t); }
      catch (error) {
        if (error.status === 403) {
          await this.api.session(t.signal);
          try { const data = verifyStatus(await this.api.status(this.intent.upload_id,t.signal),this.intent); return this.state(data,t); }
          catch (again) { if (again.status === 403) throw new Error("Consulta incompatível com os cabeçalhos de segurança deste navegador; confirme no Safari da Etapa 5."); throw again; }
        }
        throw error;
      }
    }
    if (this.file) return this.drive(t);
    activity("Envio aguardando o mesmo arquivo. Selecione-o novamente para verificar todo o conteúdo."); byId("reselect-label").hidden = false; byId("reselect").hidden = false;
  }
  async reselect(file) {
    if (!this.intent || filename(file) !== this.intent.filename || file.name !== (this.intent.raw_filename || this.intent.filename) || file.size !== this.intent.total_bytes) throw new Error("Nome ou tamanho do arquivo não corresponde ao envio salvo");
    const t = this.next(); message("Verificando novamente o arquivo completo…");
    const hashes = await hashFile(file,{signal:t.signal,progress:(n,total)=>{if(this.current(t)) activity(`Verificando: ${Math.round(n*100/total)}%.`);}});
    if (!this.current(t)) return;
    if (hashes.total !== this.intent.expected_sha256) throw new Error("Conteúdo diferente do arquivo original; envio bloqueado");
    this.file = file; this.hashes = hashes; byId("pause").hidden = false; byId("reselect-label").hidden = true; byId("reselect").hidden = true;
    await this.resume(t);
  }
  async drive(t) {
    if (this.running || !this.current(t)) return;
    this.running = true;
    const renew = setInterval(() => { if (this.current(t)) this.lease(); }, 5000);
    try {
      if (!this.lease()) { activity("Outra aba acompanha este envio. Feche-a para retomar aqui."); return; }
      let failures = 0;
      while (this.current(t) && this.intent) {
        if (!this.intent.upload_id) {
          if (!this.file) return this.resume(t);
          try { const data = await this.api.init(this.intent,t.signal); if (!this.current(t)) return; if (!ID.test(data.upload_id) || data.chunk_bytes !== CHUNK_BYTES) throw new Error("Protocolo de upload incompatível"); verifyStatus(data,this.intent); this.intent.upload_id = data.upload_id; this.setIntent(this.intent,t); }
          catch (error) { if (error.status === 429 || error.status === 503 || error.status === 0) { if (error.status === 0 && failures >= 6) throw new Error("Conexão instável. Use Tentar novamente para retomar a intenção salva."); await pause(error.retryAfter || Math.min(30000,2000*2**failures++),t.signal); continue; } throw error; }
        }
        let data = verifyStatus(await this.api.status(this.intent.upload_id,t.signal),this.intent);
        if (data.state !== "uploading" || data.current_offset === this.intent.total_bytes) { await this.state(data,t); return; }
        if (!this.file) { await this.state(data,t); return; }
        const offset = data.current_offset, end = Math.min(offset+CHUNK_BYTES,this.file.size);
        const buffer = await this.file.slice(offset,end).arrayBuffer();
        const hash = this.hashes?.chunks.get(offset)?.hash || hex(await crypto.subtle.digest("SHA-256",buffer));
        if (!this.current(t)) return;
        try { const confirmed = await this.api.patch(this.intent.upload_id,offset,buffer,hash,t.signal); if (!this.current(t)) return; this.intent.confirmed_offset = confirmed; this.setIntent(this.intent,t); activity(`Enviado e confirmado: ${Math.round(confirmed*100/this.file.size)}%.`); const progress=byId("progress"); progress.hidden=false; progress.value=confirmed*100/this.file.size; failures=0; }
        catch (error) {
          if (error.status === 409 || error.status === 0 || error.status === 429 || error.status === 503) { activity("Conferindo o último trecho recebido…"); await pause(error.retryAfter || Math.min(30000,2000*2**failures++),t.signal); if (failures > 6) throw new Error("Conexão instável. Use Tentar novamente para retomar."); continue; }
          throw error;
        }
      }
    } finally { clearInterval(renew); this.releaseLease(); this.running = false; }
  }
  async state(data,t) {
    if (!this.current(t)) return;
    if (data.recording_id) this.intent.recording_id = data.recording_id;
    if (data.job_id) this.intent.job_id = data.job_id;
    if (data.error_code === "import_outcome_unknown") throw new Error("Importação incerta; solicite reconciliação antes de reenviar.");
    this.intent.confirmed_offset = data.current_offset; this.setIntent(this.intent,t);
    if (data.state === "completed") {
      if (this.intent.job_id) return this.track(t);
      if (this.noJobChecks++ < 5) { activity("Importação concluída. Conferindo o job…"); await pause(3000,t.signal); return this.resume(t); }
      activity("O job ainda não foi confirmado. Solicite reconciliação antes de iniciar outro envio."); return;
    }
    if (data.state === "assembling" || data.state === "importing") { activity("Preparando o áudio no notebook…"); await pause(3000,t.signal); return this.resume(t); }
    if (data.state === "aborted" || data.state === "expired") throw new Error(`Sessão ${data.state}; este envio não pode continuar.`);
    if (data.state !== "uploading") throw new Error(`Estado remoto desconhecido: ${data.state}`);
    if (data.current_offset === this.intent.total_bytes) {
      activity("Finalizando envio…");
      try { const next = await this.api.finalize(this.intent,t.signal); return this.state(verifyStatus(next,this.intent),t); }
      catch(error) { if (error.status === 503 || error.status === 0 || error.status === 429) { await pause(error.retryAfter || 2000,t.signal); return this.resume(t); } throw error; }
    }
    if (!this.file) { activity(`Retomada necessária: ${bytes(data.current_offset)} de ${bytes(this.intent.total_bytes)} confirmados. Selecione o mesmo arquivo.`); byId("reselect-label").hidden=false; byId("reselect").hidden=false; return; }
    return this.drive(t);
  }
  async track(t) {
    let missingTranscript = 0;
    while (this.current(t) && this.intent?.job_id) {
      const job = await this.api.job(this.intent.job_id,t.signal); if (!this.current(t)) return;
      activity(`Transcrição: ${job.status}${job.phase ? ` · ${job.phase}` : ""}${Number.isFinite(job.progress_percent) ? ` · ${Math.round(job.progress_percent)}%` : ""}`);
      if (job.status === "failed" || job.status === "cancelled") throw new Error(job.error_message || `Job ${job.status}`);
      if (job.status === "succeeded" && job.transcript_available) { const data=await this.api.transcript(this.intent.job_id,t.signal); if (!this.current(t)) return; if (typeof data.text !== "string") throw new Error("Transcrição inválida"); renderTranscript(data); message("Transcrição pronta para leitura e cópia."); return; }
      if (job.status === "succeeded" && ++missingTranscript >= 5) { activity("Job concluído; transcrição ainda indisponível. Tente novamente mais tarde."); return; }
      await pause(3000,t.signal);
    }
  }
  stop() { this.next(); this.releaseLease(); this.running=false; byId("pause").hidden=true; byId("retry").hidden=false; activity("Envio pausado neste navegador. A sessão remota foi preservada."); }
  forget() { this.next(); this.releaseLease(); this.intent=null; this.file=null; this.hashes=null; this.noJobChecks=0; clear(); byId("activity").hidden=true; byId("result").hidden=true; byId("reselect").hidden=true; byId("reselect-label").hidden=true; byId("pause").hidden=true; byId("submit").disabled=false; for(const id of ["subject","title","lesson-date"]) byId(id).disabled=false; message("Acompanhamento removido deste navegador."); }
}
if (typeof document !== "undefined") {
  const controller = new RemoteController();
  const showError = (error) => { if (error?.name === "AbortError") return; message(error instanceof ApiError && error.status === 409 && error.message === "import_outcome_unknown" ? "Importação incerta. Peça reconciliação antes de outro envio." : error.message || "Falha inesperada"); byId("retry").hidden=false; };
  controller.bootstrap().catch(showError);
  byId("upload-form").addEventListener("submit", (event) => { event.preventDefault(); controller.start(byId("file").files[0],byId("subject").value,byId("title").value,byId("lesson-date").value).catch(showError); });
  byId("reselect").addEventListener("change", () => controller.reselect(byId("reselect").files[0]).catch(showError));
  byId("pause").addEventListener("click", () => controller.stop());
  byId("retry").addEventListener("click", () => { byId("retry").hidden=true; controller.resume().catch(showError); });
  byId("forget").addEventListener("click", () => controller.forget());
  byId("copy").addEventListener("click", () => navigator.clipboard.writeText(byId("transcript").value).then(() => message("Texto copiado."), () => message("Cópia indisponível; selecione o texto abaixo manualmente.")));
  for (const event of ["online","pageshow"]) window.addEventListener(event, () => { if (!document.hidden && controller.intent && !controller.running) controller.resume().catch(showError); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && controller.intent && !controller.running) controller.resume().catch(showError); });
  window.addEventListener("storage", (event) => { if (event.key === LEASE && controller.intent) { try { const lease=JSON.parse(event.newValue); if (lease?.owner !== controller.owner && lease?.until > Date.now()) { controller.stop(); activity("Outra aba assumiu este envio; esta aba aguarda."); } } catch { /* invalid lease */ } } });
}
