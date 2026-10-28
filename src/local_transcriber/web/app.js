import { ApiError, LocalApi } from "/assets/api.js";
import { JobEventTracker, LatestRequest, isAbortError } from "/assets/async_state.js";
import {
  byId,
  clear,
  element,
  formatBytes,
  formatDate,
  formatDateTime,
  formatDuration,
  formatPercent,
  phaseLabel,
  plainExcerpt,
  statusLabel,
  textPair,
} from "/assets/dom.js";

const api = new LocalApi();
const exportLabels = Object.freeze({ txt: "TXT", md: "Markdown", srt: "SRT", vtt: "WebVTT", json: "JSON" });
const views = Object.freeze({
  painel: ["Painel", "Visão geral"],
  materias: ["Matérias", "Organização"],
  biblioteca: ["Biblioteca", "Acervo local"],
  fila: ["Fila", "Processamento local"],
  leitura: ["Leitura", "Revisão da aula"],
  modelos: ["Modelos", "Recursos locais"],
});

const state = {
  health: null,
  capabilities: null,
  runtime: null,
  models: [],
  subjects: [],
  recordings: [],
  jobs: [],
  transcripts: [],
  searchResults: null,
  pendingJob: null,
  pendingDelete: null,
  selectedRecording: null,
  readerContext: null,
  activeStreams: new Map(),
  streamStates: new Map(),
};

const loadRequest = new LatestRequest();
const searchRequest = new LatestRequest();
const readerRequest = new LatestRequest();
const exportRequests = new Map();
const jobEvents = new JobEventTracker();

function announce(message) {
  byId("global-live").textContent = message;
}

function toast(message, kind = "info") {
  const region = byId("toast-region");
  const item = element("div", { className: "toast", text: message, dataset: { kind } });
  region.append(item);
  window.setTimeout(() => item.remove(), 5000);
}

function errorMessage(error) {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Ocorreu um erro inesperado.";
}

function setServiceState(online) {
  const wrapper = byId("service-state");
  wrapper.dataset.state = online ? "online" : "offline";
  byId("service-state-text").textContent = online ? "Serviço local ativo" : "Serviço indisponível";
  byId("connection-banner").hidden = online;
}

function setServiceLoading() {
  byId("service-state").dataset.state = "loading";
  byId("service-state-text").textContent = "Verificando serviço…";
  byId("connection-banner").hidden = true;
}

function showView(requested, moveFocus = false) {
  const name = Object.hasOwn(views, requested) ? requested : "painel";
  for (const [viewName, [title, context]] of Object.entries(views)) {
    byId(`view-${viewName}`).hidden = viewName !== name;
    const link = document.querySelector(`[data-view="${viewName}"]`);
    if (viewName === name) {
      link.setAttribute("aria-current", "page");
      byId("view-title").textContent = title;
      byId("view-context").textContent = context;
    } else {
      link.removeAttribute("aria-current");
    }
  }
  if (window.location.hash !== `#${name}`) {
    window.history.replaceState(null, "", `#${name}`);
  }
  if (moveFocus) {
    window.scrollTo(0, 0);
    byId("main-content").focus();
  }
}

function subjectName(subjectId) {
  return state.subjects.find((subject) => subject.id === subjectId)?.name || "Matéria removida";
}

function recordingFor(recordingId) {
  return state.recordings.find((recording) => recording.id === recordingId);
}

function jobsFor(recordingId) {
  return state.jobs.filter((job) => job.recording_id === recordingId);
}

function latestJob(recordingId) {
  return jobsFor(recordingId).sort((left, right) => right.created_at.localeCompare(left.created_at))[0];
}

function transcriptFor(recordingId) {
  return state.transcripts.find((transcript) => transcript.recording_id === recordingId);
}

function renderDashboard() {
  if (!state.health) {
    byId("dashboard-service").textContent = "Indisponível";
    byId("dashboard-schema").textContent = "Sem resposta local";
  } else {
    byId("dashboard-service").textContent = "Ativo";
    byId("dashboard-schema").textContent = `Versão ${state.health.version} · schema v${state.health.schema_version}`;
    byId("sidebar-version").textContent = `Versão ${state.health.version}`;
  }

  if (state.runtime) {
    byId("dashboard-worker").textContent = state.runtime.worker_running ? "Em execução" : "Parado";
    byId("dashboard-profile").textContent = state.runtime.recommended_profile === "cuda" ? "CUDA" : "CPU";
    byId("dashboard-runtime").textContent = state.runtime.cuda_available
      ? "CUDA disponível"
      : "CPU disponível · CUDA indisponível";
  } else {
    byId("dashboard-worker").textContent = "Não verificado";
    byId("dashboard-profile").textContent = "Não verificado";
    byId("dashboard-runtime").textContent = "Runtime indisponível";
  }

  const installed = state.models.filter((model) => model.installed).length;
  byId("dashboard-models").textContent = `${installed} de ${state.models.length}`;
  const recent = clear(byId("recent-jobs"));
  recent.setAttribute("aria-busy", "false");
  if (state.jobs.length === 0) {
    recent.append(emptyContent("Nenhum job ainda", "Inicie uma transcrição pela biblioteca."));
    return;
  }
  const list = element("ul", { className: "plain-list" });
  for (const job of state.jobs.slice(0, 5)) {
    const recording = recordingFor(job.recording_id);
    const details = element("div", { className: "primary-cell" }, [
      element("strong", { text: recording?.title || "Gravação não encontrada" }),
      element("span", { text: `${phaseLabel(job.phase)} · ${formatDateTime(job.updated_at)}` }),
    ]);
    const badge = element("span", {
      className: "status-badge",
      text: statusLabel(job.status),
      dataset: { status: job.status },
    });
    list.append(element("li", {}, [details, badge]));
  }
  recent.append(list);
}

function emptyContent(title, description) {
  return element("div", { className: "empty-state" }, [
    element("strong", { text: title }),
    element("p", { text: description }),
  ]);
}

function renderSubjects() {
  byId("subject-count").textContent = String(state.subjects.length);
  const list = clear(byId("subject-list"));
  if (state.subjects.length === 0) {
    list.append(element("li", {}, [element("span", { text: "Nenhuma matéria cadastrada." })]));
  }
  for (const subject of state.subjects) {
    const info = element("div", { className: "primary-cell" }, [
      element("strong", { text: subject.name }),
      element("small", { text: `${state.recordings.filter((item) => item.subject_id === subject.id).length} gravação(ões)` }),
    ]);
    const filter = element("button", { className: "button button-quiet", text: "Ver aulas", type: "button" });
    filter.addEventListener("click", () => {
      searchRequest.invalidate();
      byId("subject-filter").value = subject.id;
      state.searchResults = null;
      byId("search-query").value = "";
      renderRecordings();
      showView("biblioteca", true);
    });
    list.append(element("li", {}, [info, filter]));
  }
  renderSubjectOptions();
}

function appendOption(select, value, label) {
  const option = element("option", { text: label });
  option.value = value;
  select.append(option);
}

function renderSubjectOptions() {
  const upload = byId("upload-subject");
  const filter = byId("subject-filter");
  const uploadValue = upload.value;
  const filterValue = filter.value;
  clear(upload);
  clear(filter);
  appendOption(filter, "", "Todas as matérias");
  if (state.subjects.length === 0) {
    appendOption(upload, "", "Crie uma matéria primeiro");
    upload.disabled = true;
    byId("upload-submit").disabled = true;
  } else {
    upload.disabled = false;
    byId("upload-submit").disabled = false;
    appendOption(upload, "", "Selecione uma matéria");
    for (const subject of state.subjects) {
      appendOption(upload, subject.id, subject.name);
      appendOption(filter, subject.id, subject.name);
    }
    upload.value = state.subjects.some((item) => item.id === uploadValue) ? uploadValue : "";
    filter.value = state.subjects.some((item) => item.id === filterValue) ? filterValue : "";
  }
}

function recordingStatus(recording) {
  if (transcriptFor(recording.id)) {
    return ["succeeded", "Transcrição pronta"];
  }
  const job = latestJob(recording.id);
  if (job) {
    return [job.status, statusLabel(job.status)];
  }
  return ["ready", "Pronta para transcrever"];
}

function visibleRecordings() {
  const subjectId = byId("subject-filter").value;
  let recordings = subjectId
    ? state.recordings.filter((recording) => recording.subject_id === subjectId)
    : [...state.recordings];
  if (state.searchResults !== null) {
    const matches = new Set(state.searchResults.map((result) => result.recording_id));
    recordings = recordings.filter((recording) => matches.has(recording.id));
  }
  return recordings;
}

function renderRecordings() {
  const rows = clear(byId("recording-rows"));
  const recordings = visibleRecordings();
  const panel = byId("recordings-panel");
  panel.setAttribute("aria-busy", "false");
  byId("recordings-empty").hidden = recordings.length !== 0;
  const query = byId("search-query").value.trim();
  byId("library-summary").textContent = query
    ? `${recordings.length} resultado(s) para “${query}”.`
    : `${recordings.length} gravação(ões) exibida(s).`;

  const excerpts = new Map((state.searchResults || []).map((result) => [result.recording_id, result.excerpt]));
  for (const recording of recordings) {
    const [status, label] = recordingStatus(recording);
    const titleChildren = [
      element("strong", { text: recording.title }),
      element("span", { text: formatDate(recording.lesson_date) }),
    ];
    if (excerpts.has(recording.id)) {
      titleChildren.push(element("span", { text: plainExcerpt(excerpts.get(recording.id)) }));
    }
    const title = element("td", {}, [element("div", { className: "primary-cell" }, titleChildren)]);
    const subject = element("td", { text: subjectName(recording.subject_id) });
    const media = element("td", {}, [
      element("div", { className: "primary-cell" }, [
        element("span", { className: "media-detail", text: recording.media_format.toUpperCase() }),
        element("span", { className: "media-detail", text: `${formatDuration(recording.duration_seconds)} · ${formatBytes(recording.size_bytes)}` }),
      ]),
    ]);
    const statusCell = element("td", {}, [
      element("span", {
        className: status === "ready" ? "local-badge" : "status-badge",
        text: label,
        dataset: { status },
      }),
    ]);
    const actions = element("div", { className: "row-actions" });
    if (transcriptFor(recording.id)) {
      const read = element("button", { className: "button button-secondary", text: "Ler", type: "button" });
      read.addEventListener("click", () => openReader(recording.id));
      actions.append(read);
    } else {
      const transcribe = element("button", { className: "button button-secondary", text: "Transcrever", type: "button" });
      transcribe.addEventListener("click", () => openTranscriptionDialog(recording.id));
      actions.append(transcribe);
    }
    const remove = element("button", { className: "button button-quiet", text: "Excluir", type: "button" });
    remove.addEventListener("click", () => openDeleteDialog(recording.id));
    actions.append(remove);
    rows.append(element("tr", {}, [title, subject, media, statusCell, element("td", {}, [actions])]));
  }
}

function jobCard(job) {
  const recording = recordingFor(job.recording_id);
  const heading = element("div", { className: "job-card-title" }, [
    element("strong", { text: recording?.title || "Gravação não encontrada" }),
    element("span", { text: `${job.model_name} · tentativa ${job.attempt_count}/${job.max_attempts}` }),
  ]);
  const badge = element("span", {
    className: "status-badge",
    text: job.cancel_requested_at && job.status === "running" ? "Cancelamento solicitado" : statusLabel(job.status),
    dataset: { status: job.status },
  });
  const progress = element("progress", {
    className: "job-progress",
    attributes: { max: "100", "aria-label": `Progresso de ${recording?.title || "transcrição"}` },
  });
  if (Number.isFinite(job.progress_percent)) {
    progress.value = job.progress_percent;
  }
  const timing = job.total_seconds
    ? `${formatDuration(job.processed_seconds)} de ${formatDuration(job.total_seconds)}`
    : `${formatDuration(job.processed_seconds)} processados`;
  const phase = element("div", {}, [
    element("strong", { text: phaseLabel(job.phase) }),
    element("p", { text: `${formatPercent(job.progress_percent)} · ${timing}` }),
  ]);
  const actions = element("div", { className: "row-actions" });
  if (["pending", "running"].includes(job.status)) {
    const cancel = element("button", {
      className: "button button-quiet",
      text: job.cancel_requested_at ? "Cancelamento pendente" : "Cancelar",
      type: "button",
    });
    cancel.disabled = Boolean(job.cancel_requested_at);
    cancel.addEventListener("click", () => cancelJob(job.id));
    actions.append(cancel);
  }
  if (["failed", "cancelled"].includes(job.status)) {
    const retry = element("button", { className: "button button-secondary", text: "Tentar novamente", type: "button" });
    retry.addEventListener("click", () => retryJob(job.id));
    actions.append(retry);
  }
  if (job.status === "succeeded") {
    const read = element("button", { className: "button button-secondary", text: "Ler transcrição", type: "button" });
    read.addEventListener("click", () => openReader(job.recording_id));
    actions.append(read);
  }
  const card = element("article", { className: "job-card" }, [
    element("div", { className: "job-card-header" }, [heading, badge]),
    progress,
    element("div", { className: "job-card-footer" }, [phase, actions]),
  ]);
  if (job.error_message) {
    const details = element("details", { className: "job-error" }, [
      element("summary", { text: "A transcrição não foi concluída. Ver detalhes técnicos" }),
      element("p", { text: job.error_message }),
    ]);
    card.append(details);
  }
  return card;
}

function renderJobs() {
  const list = clear(byId("job-list"));
  list.setAttribute("aria-busy", "false");
  if (state.jobs.length === 0) {
    list.append(emptyContent("Fila vazia", "As novas transcrições aparecerão aqui."));
  } else {
    for (const job of state.jobs) {
      list.append(jobCard(job));
    }
  }
  renderStreamState();
}

function renderStreamState() {
  const active = state.jobs.filter((job) => ["pending", "running"].includes(job.status));
  const label = byId("sse-state");
  if (active.length === 0) {
    label.textContent = "Nenhum job ativo. A fila será recuperada ao recarregar a página.";
    return;
  }
  const reconnecting = active.some((job) => state.streamStates.get(job.id) === "reconnecting");
  if (reconnecting) {
    label.textContent = "Eventos desconectados. Reconectando automaticamente e recuperando eventos persistidos…";
  } else {
    label.textContent = `Acompanhando ${active.length} job(s) por eventos persistentes.`;
  }
}

function renderModels() {
  const list = clear(byId("model-list"));
  list.setAttribute("aria-busy", "false");
  for (const model of state.models) {
    const identity = element("div", {}, [
      element("strong", { text: model.name }),
      element("span", {
        className: model.installed ? "status-badge" : "local-badge",
        text: model.installed ? "Instalado" : "Ausente",
        dataset: { status: model.installed ? "succeeded" : "ready" },
      }),
    ]);
    const description = element("p", {
      text: model.installed
        ? "Disponível para novas transcrições neste computador."
        : "A interface não baixa modelos. Execute o comando abaixo em um terminal quando desejar instalar.",
    });
    const action = model.required_action
      ? element("code", { text: model.required_action })
      : element("span", { text: "Pronto para uso" });
    list.append(element("article", { className: "model-card" }, [identity, description, action]));
  }
  renderModelOptions();
}

function renderModelOptions() {
  const select = byId("transcription-model");
  const previous = select.value;
  clear(select);
  for (const model of state.models) {
    appendOption(select, model.name, `${model.name}${model.installed ? " · instalado" : " · ausente"}`);
  }
  if (state.models.some((model) => model.name === previous)) {
    select.value = previous;
  } else {
    select.value = state.models.find((model) => model.installed)?.name || state.models[0]?.name || "";
  }
  updateTranscriptionWarning();
}

function updateTranscriptionWarning() {
  const model = state.models.find((item) => item.name === byId("transcription-model").value);
  const profile = byId("transcription-profile").value;
  const warning = byId("transcription-model-warning");
  const messages = [];
  if (model && !model.installed) {
    messages.push(`Modelo ausente. Instale explicitamente com: ${model.required_action}`);
  }
  if (profile === "cuda" && state.runtime && !state.runtime.cuda_available) {
    messages.push("CUDA não está disponível no runtime atual. Escolha Automático ou CPU.");
  }
  warning.textContent = messages.join(" ");
  warning.hidden = messages.length === 0;
  byId("review-transcription").disabled = messages.length > 0 || !model;
}

function renderAll() {
  renderSubjects();
  renderRecordings();
  renderJobs();
  renderModels();
  renderDashboard();
}

function jobSequence(job) {
  return Number.isSafeInteger(job.last_event_sequence) && job.last_event_sequence >= 0
    ? job.last_event_sequence
    : 0;
}

function replaceJob(job) {
  const index = state.jobs.findIndex((item) => item.id === job.id);
  const knownSequence = jobEvents.lastSequence(job.id);
  if (index !== -1 && jobSequence(job) < knownSequence) {
    return false;
  }
  jobEvents.seed(job.id, jobSequence(job));
  if (index === -1) {
    state.jobs.unshift(job);
  } else {
    state.jobs[index] = job;
  }
  state.jobs.sort((left, right) => right.created_at.localeCompare(left.created_at));
  return true;
}

function replaceJobSnapshot(jobs) {
  const previous = new Map(state.jobs.map((job) => [job.id, job]));
  state.jobs = jobs.map((job) => {
    const existing = previous.get(job.id);
    if (existing && jobSequence(job) < jobEvents.lastSequence(job.id)) {
      return existing;
    }
    jobEvents.seed(job.id, jobSequence(job));
    return job;
  });
  state.jobs.sort((left, right) => right.created_at.localeCompare(left.created_at));
  jobEvents.retain(new Set(state.jobs.map((job) => job.id)));
}

async function loadAll() {
  const request = loadRequest.begin("global");
  setServiceLoading();
  const tasks = await Promise.allSettled([
    api.health({ signal: request.signal }),
    api.capabilities({ signal: request.signal }),
    api.runtime({ signal: request.signal }),
    api.models({ signal: request.signal }),
    api.subjects({ signal: request.signal }),
    api.recordings("", { signal: request.signal }),
    api.jobs({ signal: request.signal }),
    api.transcripts("", { signal: request.signal }),
  ]);
  if (!loadRequest.isCurrent(request, "global")) {
    return;
  }
  const [health, capabilities, runtime, models, subjects, recordings, jobs, transcripts] = tasks;
  if (health.status === "rejected") {
    setServiceState(false);
    renderAll();
    return;
  }
  state.health = health.value;
  state.capabilities = capabilities.status === "fulfilled" ? capabilities.value : null;
  state.runtime = runtime.status === "fulfilled" ? runtime.value : null;
  state.models = models.status === "fulfilled" ? models.value : [];
  state.subjects = subjects.status === "fulfilled" ? subjects.value : [];
  state.recordings = recordings.status === "fulfilled" ? recordings.value : [];
  replaceJobSnapshot(jobs.status === "fulfilled" ? jobs.value : []);
  state.transcripts = transcripts.status === "fulfilled" ? transcripts.value : [];
  const failures = tasks.slice(1).filter((task) => task.status === "rejected").length;
  setServiceState(true);
  renderAll();
  connectActiveJobs();
  if (failures > 0) {
    toast("Parte dos dados não pôde ser carregada. Tente atualizar.", "error");
  }
}

function connectActiveJobs() {
  const knownIds = new Set(state.jobs.map((job) => job.id));
  for (const job of state.jobs) {
    jobEvents.seed(job.id, jobSequence(job));
  }
  const activeIds = new Set(
    state.jobs.filter((job) => ["pending", "running"].includes(job.status)).map((job) => job.id),
  );
  for (const [jobId, stream] of state.activeStreams.entries()) {
    if (!activeIds.has(jobId)) {
      stream.close();
      jobEvents.stop(stream.token, { clear: !knownIds.has(jobId) });
      state.activeStreams.delete(jobId);
      state.streamStates.delete(jobId);
    }
  }
  jobEvents.retain(knownIds);
  for (const jobId of activeIds) {
    if (state.activeStreams.has(jobId)) {
      continue;
    }
    const job = state.jobs.find((item) => item.id === jobId);
    const token = jobEvents.begin(jobId, jobSequence(job));
    state.streamStates.set(jobId, "connecting");
    const close = api.eventStream(jobId, {
      open: () => {
        if (!jobEvents.isCurrent(token)) {
          return;
        }
        state.streamStates.set(jobId, "connected");
        renderStreamState();
      },
      error: () => {
        if (!jobEvents.isCurrent(token)) {
          return;
        }
        state.streamStates.set(jobId, "reconnecting");
        renderStreamState();
      },
      invalid: () => {
        if (jobEvents.isCurrent(token)) {
          toast("Um evento de progresso inválido foi ignorado.", "error");
        }
      },
      message: (event, eventId) => {
        if (jobEvents.accept(token, eventId, event.sequence)) {
          updateJobFromEvent(jobId, event, token);
        }
      },
    }, { afterSequence: jobEvents.cursor(token) });
    state.activeStreams.set(jobId, { close, token });
  }
  renderStreamState();
}

async function updateJobFromEvent(jobId, event, token) {
  if (!jobEvents.isCurrent(token)) {
    return;
  }
  const current = state.jobs.find((job) => job.id === jobId);
  if (!current) {
    return;
  }
  replaceJob({
    ...current,
    status: event.status,
    phase: event.phase,
    progress_percent: event.percent ?? current.progress_percent,
    processed_seconds: event.processed_seconds ?? current.processed_seconds,
    total_seconds: event.total_seconds ?? current.total_seconds,
    updated_at: event.created_at || current.updated_at,
    last_event_sequence: event.sequence,
  });
  renderJobs();
  renderDashboard();
  renderRecordings();
  announce(`${recordingFor(current.recording_id)?.title || "Transcrição"}: ${phaseLabel(event.phase)}, ${formatPercent(event.percent)}.`);
  if (["succeeded", "failed", "cancelled"].includes(event.status)) {
    try {
      const job = await api.job(jobId);
      if (!jobEvents.isCurrent(token)) {
        return;
      }
      replaceJob(job);
      const transcripts = await api.transcripts();
      if (!jobEvents.isCurrent(token)) {
        return;
      }
      state.transcripts = transcripts;
    } catch (error) {
      if (jobEvents.isCurrent(token) && !isAbortError(error)) {
        toast(errorMessage(error), "error");
      }
    }
    if (!jobEvents.isCurrent(token)) {
      return;
    }
    const stream = state.activeStreams.get(jobId);
    stream?.close();
    jobEvents.stop(token);
    state.activeStreams.delete(jobId);
    state.streamStates.delete(jobId);
    renderAll();
    connectActiveJobs();
  }
}

async function cancelJob(jobId) {
  try {
    replaceJob(await api.cancelJob(jobId));
    renderAll();
    connectActiveJobs();
    announce("Cancelamento solicitado.");
  } catch (error) {
    toast(errorMessage(error), "error");
  }
}

async function retryJob(jobId) {
  try {
    replaceJob(await api.retryJob(jobId));
    renderAll();
    connectActiveJobs();
    announce("Job recolocado na fila.");
  } catch (error) {
    toast(errorMessage(error), "error");
  }
}

function openTranscriptionDialog(recordingId) {
  const recording = recordingFor(recordingId);
  if (!recording) {
    toast("Gravação não encontrada.", "error");
    return;
  }
  byId("transcription-recording-id").value = recording.id;
  byId("transcription-recording-title").textContent = `${recording.title} · ${subjectName(recording.subject_id)}`;
  renderModelOptions();
  byId("transcription-dialog").showModal();
}

function buildPendingJob() {
  const recording = recordingFor(byId("transcription-recording-id").value);
  const model = state.models.find((item) => item.name === byId("transcription-model").value);
  if (!recording || !model?.installed) {
    throw new ApiError("Escolha uma gravação e um modelo instalado.");
  }
  return {
    recording,
    payload: {
      recording_id: recording.id,
      model_name: model.name,
      language: byId("transcription-language").value || null,
      profile: byId("transcription-profile").value,
      beam_size: Number(byId("transcription-beam").value),
      vad_filter: byId("transcription-vad").checked,
      word_timestamps: byId("transcription-timestamps").checked,
    },
  };
}

function renderTranscriptionSummary(pending) {
  const summary = clear(byId("transcription-summary"));
  const items = [
    ["Gravação", pending.recording.title],
    ["Modelo", pending.payload.model_name],
    ["Idioma", pending.payload.language === "pt" ? "Português" : "Detecção automática"],
    ["Perfil", pending.payload.profile.toUpperCase()],
    ["Beam size", pending.payload.beam_size],
    ["VAD", pending.payload.vad_filter ? "Ativado" : "Desativado"],
    ["Timestamps", pending.payload.word_timestamps ? "Por palavra" : "Somente segmentos"],
  ];
  for (const [label, value] of items) {
    summary.append(element("dt", { text: label }), element("dd", { text: value }));
  }
}

function openDeleteDialog(recordingId) {
  const recording = recordingFor(recordingId);
  if (!recording) {
    return;
  }
  state.pendingDelete = recording;
  byId("delete-message").textContent = `Excluir “${recording.title}”?`;
  byId("delete-dialog").showModal();
}

async function openReader(recordingId) {
  const recording = recordingFor(recordingId);
  if (!recording) {
    toast("Gravação não encontrada.", "error");
    return;
  }
  const request = readerRequest.begin(recordingId);
  state.readerContext = null;
  try {
    const transcripts = await api.transcripts(recordingId, { signal: request.signal });
    if (!readerRequest.isCurrent(request, recordingId)) {
      return;
    }
    if (transcripts.length === 0) {
      throw new ApiError("Esta gravação ainda não possui transcrição concluída.");
    }
    const transcript = transcripts[0];
    const artifacts = await api.exports(transcript.id, { signal: request.signal });
    if (!readerRequest.isCurrent(request, recordingId)) {
      return;
    }
    const currentRecording = recordingFor(recordingId);
    if (!currentRecording) {
      throw new ApiError("Gravação não encontrada.");
    }
    state.readerContext = {
      generation: request.generation,
      recordingId,
      transcriptId: transcript.id,
    };
    state.selectedRecording = currentRecording;
    renderReader(currentRecording, transcript, artifacts);
    loadSummary(transcript.id, request.signal);
    showView("leitura", true);
  } catch (error) {
    if (readerRequest.isCurrent(request, recordingId) && !isAbortError(error)) {
      toast(errorMessage(error), "error");
    }
  }
}

function mediaPlayerFor(recording) {
  const videoFormats = new Set(["mp4", "mkv", "webm"]);
  const video = byId("video-player");
  const audio = byId("audio-player");
  const selected = videoFormats.has(recording.media_format.toLowerCase()) ? video : audio;
  const other = selected === video ? audio : video;
  other.pause();
  other.removeAttribute("src");
  other.hidden = true;
  selected.src = `/api/recordings/${encodeURIComponent(recording.id)}/media`;
  selected.hidden = false;
  return selected;
}

function addMetric(container, label, value) {
  container.append(textPair(label, value, "metric"));
}

function renderReader(recording, transcript, exports) {
  byId("reader-empty").hidden = true;
  byId("reader-content").hidden = false;
  byId("reader-title").textContent = recording.title;
  byId("reader-subtitle").textContent = `${subjectName(recording.subject_id)} · ${formatDate(recording.lesson_date)}`;
  byId("reader-metadata").textContent = `${recording.original_name} · ${formatDuration(recording.duration_seconds)}`;
  byId("transcript-full-text").textContent = transcript.text;
  const player = mediaPlayerFor(recording);
  const metrics = clear(byId("transcript-metrics"));
  addMetric(metrics, "Idioma", transcript.language || "Não identificado");
  if (transcript.language_probability !== null) {
    addMetric(metrics, "Confiança do idioma", formatPercent(transcript.language_probability * 100, 1));
  }
  if (transcript.metrics) {
    addMetric(metrics, "Duração", formatDuration(transcript.metrics.audio_duration_seconds));
    addMetric(metrics, "Processamento", formatDuration(transcript.metrics.processing_duration_seconds));
    addMetric(metrics, "Segmentos", String(transcript.metrics.segment_count));
    addMetric(metrics, "Palavras", String(transcript.metrics.word_count));
  }

  byId("segment-count").textContent = String(transcript.segments.length);
  const segments = clear(byId("segment-list"));
  for (const segment of transcript.segments) {
    const seek = element("button", {
      className: "timestamp-button",
      text: formatDuration(segment.start_seconds),
      type: "button",
      title: `Ir para ${formatDuration(segment.start_seconds)}`,
    });
    const copy = element("div", { className: "segment-copy" }, [element("p", { text: segment.text })]);
    const wordsWithProbability = segment.words.filter((word) => word.probability !== null);
    if (wordsWithProbability.length > 0) {
      const words = element("div", { className: "word-list", attributes: { "aria-label": "Confiança por palavra" } });
      for (const word of wordsWithProbability) {
        words.append(element("span", {
          className: "word-confidence",
          text: `${word.text} ${formatPercent(word.probability * 100, 0)}`,
        }));
      }
      copy.append(words);
    }
    const li = element("li", { className: "segment-item" }, [seek, copy]);
    seek.addEventListener("click", () => {
      player.currentTime = segment.start_seconds;
      player.focus();
      player.play().catch(() => undefined);
      for (const child of segments.children) {
        child.classList.remove("is-active");
      }
      li.classList.add("is-active");
    });
    segments.append(li);
  }

  const btnCopyFull = byId("btn-copy-full-text");
  if (btnCopyFull) {
    btnCopyFull.onclick = () => {
      if (navigator.clipboard && transcript.text) {
        navigator.clipboard.writeText(transcript.text)
          .then(() => toast("Texto integral copiado para a área de transferência!"))
          .catch(() => toast("Não foi possível copiar.", "error"));
      }
    };
  }

  renderExports(transcript.id, exports);
}

function renderExports(transcriptId, artifacts) {
  const container = clear(byId("export-actions"));
  const available = new Map(artifacts.map((artifact) => [artifact.kind, artifact]));
  for (const format of Object.keys(exportLabels)) {
    const artifact = available.get(format);
    if (artifact) {
      container.append(element("a", {
        className: "button button-secondary",
        text: exportLabels[format],
        href: `/api/exports/${encodeURIComponent(artifact.id)}`,
        attributes: { download: `transcricao.${format}` },
      }));
    } else {
      const create = element("button", {
        className: "button button-quiet",
        text: `Gerar ${exportLabels[format]}`,
        type: "button",
      });
      create.addEventListener("click", () => createExport(transcriptId, format, create));
      container.append(create);
    }
  }
}

async function createExport(transcriptId, format, button) {
  const readerContext = state.readerContext;
  if (!readerContext || readerContext.transcriptId !== transcriptId) {
    return;
  }
  const key = `${transcriptId}:${format}`;
  const scope = exportRequests.get(key) || new LatestRequest();
  exportRequests.set(key, scope);
  const request = scope.begin(key, { abortable: false });
  button.disabled = true;
  try {
    const artifact = await api.createExport(transcriptId, format);
    if (!scope.isCurrent(request, key)) {
      return;
    }
    if (artifact.transcript_id !== transcriptId || artifact.kind !== format) {
      throw new ApiError("A exportação retornada não corresponde ao artefato solicitado.");
    }
    const download = element("a", {
      href: `/api/exports/${encodeURIComponent(artifact.id)}`,
      attributes: { download: `transcricao.${artifact.kind}` },
    });
    document.body.append(download);
    download.click();
    download.remove();
    if (!isReaderContextCurrent(readerContext)) {
      return;
    }
    const artifacts = await api.exports(transcriptId);
    if (!scope.isCurrent(request, key) || !isReaderContextCurrent(readerContext)) {
      return;
    }
    renderExports(transcriptId, artifacts);
    toast(`${exportLabels[format]} gerado. O download foi iniciado.`);
  } catch (error) {
    if (
      scope.isCurrent(request, key) &&
      isReaderContextCurrent(readerContext) &&
      !isAbortError(error)
    ) {
      toast(errorMessage(error), "error");
    }
  } finally {
    if (scope.isCurrent(request, key)) {
      exportRequests.delete(key);
      if (isReaderContextCurrent(readerContext) && button.isConnected) {
        button.disabled = false;
      }
    }
  }
}

function isReaderContextCurrent(context) {
  return (
    state.readerContext === context &&
    readerRequest.generation === context.generation &&
    state.selectedRecording?.id === context.recordingId
  );
}

function parseTimestampSeconds(timestamp) {
  if (typeof timestamp === "number" && Number.isFinite(timestamp)) {
    return Math.max(0, timestamp);
  }
  if (!timestamp || typeof timestamp !== "string") {
    return 0;
  }
  const cleaned = timestamp.trim().replace(",", ".");
  const parts = cleaned.split(":");
  try {
    if (parts.length === 3) {
      return parseInt(parts[0], 10) * 3600 + parseInt(parts[1], 10) * 60 + parseFloat(parts[2]);
    }
    if (parts.length === 2) {
      return parseInt(parts[0], 10) * 60 + parseFloat(parts[1]);
    }
    return parseFloat(parts[0]) || 0;
  } catch (_e) {
    return 0;
  }
}

function seekActivePlayer(seconds) {
  const video = byId("video-player");
  const audio = byId("audio-player");
  const player = (video && !video.hidden) ? video : audio;
  if (player && Number.isFinite(seconds)) {
    player.currentTime = Math.max(0, seconds);
    player.focus();
    player.play().catch(() => undefined);
  }
}

let summaryTimerInterval = null;
let summaryElapsedSeconds = 0;

function formatSummaryTimer(totalSeconds) {
  const mins = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const secs = String(totalSeconds % 60).padStart(2, "0");
  return `${mins}:${secs}`;
}

function startSummaryTimer() {
  stopSummaryTimer();
  summaryElapsedSeconds = 0;
  const timerEl = byId("summary-progress-timer");
  if (timerEl) {
    timerEl.textContent = "00:00";
  }
  summaryTimerInterval = setInterval(() => {
    summaryElapsedSeconds++;
    const timer = byId("summary-progress-timer");
    if (timer) {
      timer.textContent = formatSummaryTimer(summaryElapsedSeconds);
    }
  }, 1000);
}

function stopSummaryTimer() {
  if (summaryTimerInterval !== null) {
    clearInterval(summaryTimerInterval);
    summaryTimerInterval = null;
  }
}

function updateSummaryProgress(percent, message) {
  const panel = byId("summary-status-indicator");
  const progressBar = byId("summary-progress-bar");
  const progressPercent = byId("summary-progress-percent");
  const statusText = byId("summary-status-text");

  if (panel) {
    panel.hidden = false;
    panel.classList.remove("is-error");
  }

  if (typeof percent === "number" && Number.isFinite(percent)) {
    const clamped = Math.min(100, Math.max(0, Math.round(percent)));
    if (progressBar) {
      progressBar.style.width = `${clamped}%`;
      progressBar.setAttribute("aria-valuenow", String(clamped));
      if (clamped === 100) {
        progressBar.classList.add("is-complete");
      } else {
        progressBar.classList.remove("is-complete");
      }
    }
    if (progressPercent) {
      progressPercent.textContent = `${clamped}%`;
    }
  }

  if (message && statusText) {
    statusText.textContent = message;
  }
}

function resetSummaryUI() {
  stopSummaryTimer();
  const emptyState = byId("summary-empty-state");
  const contentState = byId("summary-content");
  const indicator = byId("summary-status-indicator");
  const progressBar = byId("summary-progress-bar");
  const progressPercent = byId("summary-progress-percent");
  const progressTimer = byId("summary-progress-timer");
  const btnGen = byId("btn-generate-summary");
  const btnGenText = byId("btn-generate-summary-text");
  const downloadGroup = byId("summary-download-group");

  if (emptyState) emptyState.hidden = false;
  if (contentState) contentState.hidden = true;
  if (indicator) {
    indicator.hidden = true;
    indicator.classList.remove("is-error");
  }
  if (progressBar) {
    progressBar.style.width = "0%";
    progressBar.setAttribute("aria-valuenow", "0");
    progressBar.classList.remove("is-complete");
  }
  if (progressPercent) progressPercent.textContent = "0%";
  if (progressTimer) progressTimer.textContent = "00:00";
  if (downloadGroup) downloadGroup.hidden = true;

  if (btnGen) {
    btnGen.disabled = false;
    const provider = byId("summary-provider-select")?.value || "ollama";
    if (btnGenText) {
      btnGenText.textContent = provider === "chatgpt"
        ? "Gerar Resumo com ChatGPT"
        : provider === "antigravity"
        ? "Gerar Resumo com Antigravity"
        : "Gerar Resumo com Ollama";
    }
  }

  const thesisEl = byId("summary-core-thesis");
  if (thesisEl) thesisEl.textContent = "";

  const parasEl = byId("summary-executive-paragraphs");
  if (parasEl) clear(parasEl);

  const spokenEl = byId("summary-spoken-text");
  if (spokenEl) spokenEl.textContent = "";

  const glossaryBody = byId("summary-glossary-body");
  if (glossaryBody) clear(glossaryBody);

  const chartsGrid = byId("summary-charts-grid");
  if (chartsGrid) clear(chartsGrid);

  const flashcardsGrid = byId("summary-flashcards-grid");
  if (flashcardsGrid) clear(flashcardsGrid);
}

function createSvgChart(chart) {
  const svgNs = ["ht", "tp:", "//www.w3.org/2000/svg"].join("");
  const createSvgElement = (tag) => document.createElementNS(svgNs, tag);

  const type = String(chart.chart_type || "column").toLowerCase();
  const rawData = Array.isArray(chart.data) ? chart.data : [];
  const items = rawData.map((d, i) => {
    const label = String(d.category || d.label || d.topic || d.name || d.time || `Item ${i + 1}`);
    const val = Number(d.value ?? d.count ?? d.duration ?? d.percent ?? (10 * (i + 1)));
    return { label, val: isNaN(val) ? 10 : val };
  });

  const width = 480;
  const height = 210;
  const padding = { top: 24, right: 20, bottom: 38, left: 45 };

  const svg = createSvgElement("svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "chart-svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", chart.title || "Gráfico de dados");

  if (items.length === 0) {
    const text = createSvgElement("text");
    text.setAttribute("x", String(width / 2));
    text.setAttribute("y", String(height / 2));
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("fill", "#64748b");
    text.setAttribute("font-size", "13");
    text.textContent = "Sem pontos de dados para este gráfico";
    svg.append(text);
    return svg;
  }

  const colors = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#db2777", "#0891b2", "#4f46e5", "#0d9488"];

  if (type === "pie" || type === "donut") {
    const cx = 130;
    const cy = height / 2;
    const rOuter = 72;
    const rInner = 40;
    const total = items.reduce((acc, it) => acc + Math.max(0.1, it.val), 0);
    let currentAngle = -Math.PI / 2;

    const gSlices = createSvgElement("g");

    items.forEach((it, idx) => {
      const sliceAngle = (Math.max(0.1, it.val) / total) * (Math.PI * 2);
      const endAngle = currentAngle + sliceAngle;
      const c = colors[idx % colors.length];

      const x1Outer = cx + rOuter * Math.cos(currentAngle);
      const y1Outer = cy + rOuter * Math.sin(currentAngle);
      const x2Outer = cx + rOuter * Math.cos(endAngle);
      const y2Outer = cy + rOuter * Math.sin(endAngle);

      const x1Inner = cx + rInner * Math.cos(endAngle);
      const y1Inner = cy + rInner * Math.sin(endAngle);
      const x2Inner = cx + rInner * Math.cos(currentAngle);
      const y2Inner = cy + rInner * Math.sin(currentAngle);

      const largeArc = sliceAngle > Math.PI ? 1 : 0;
      const pathD = `M ${x1Outer.toFixed(1)} ${y1Outer.toFixed(1)} A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${x2Outer.toFixed(1)} ${y2Outer.toFixed(1)} L ${x1Inner.toFixed(1)} ${y1Inner.toFixed(1)} A ${rInner} ${rInner} 0 ${largeArc} 0 ${x2Inner.toFixed(1)} ${y2Inner.toFixed(1)} Z`;

      const path = createSvgElement("path");
      path.setAttribute("d", pathD);
      path.setAttribute("fill", c);
      path.setAttribute("stroke", "#ffffff");
      path.setAttribute("stroke-width", "1.5");
      const titleEl = createSvgElement("title");
      titleEl.textContent = `${it.label}: ${it.val} (${Math.round((it.val / total) * 100)}%)`;
      path.append(titleEl);
      gSlices.append(path);

      currentAngle = endAngle;
    });
    svg.append(gSlices);

    const gLegend = createSvgElement("g");
    gLegend.setAttribute("transform", `translate(245, 24)`);
    items.slice(0, 6).forEach((it, idx) => {
      const c = colors[idx % colors.length];
      const y = idx * 26;
      const rect = createSvgElement("rect");
      rect.setAttribute("x", "0");
      rect.setAttribute("y", String(y));
      rect.setAttribute("width", "11");
      rect.setAttribute("height", "11");
      rect.setAttribute("rx", "2.5");
      rect.setAttribute("fill", c);
      gLegend.append(rect);

      const text = createSvgElement("text");
      text.setAttribute("x", "18");
      text.setAttribute("y", String(y + 9.5));
      text.setAttribute("fill", "#334155");
      text.setAttribute("font-size", "11");
      text.setAttribute("font-weight", "500");
      const pct = Math.round((it.val / total) * 100);
      const shortLabel = it.label.length > 20 ? it.label.slice(0, 18) + "…" : it.label;
      text.textContent = `${shortLabel} (${pct}%)`;
      gLegend.append(text);
    });
    svg.append(gLegend);

  } else if (type === "line") {
    const plotW = width - padding.left - padding.right;
    const plotH = height - padding.top - padding.bottom;
    const maxVal = Math.max(...items.map(d => d.val), 1) * 1.15;

    const gGrid = createSvgElement("g");
    for (let i = 0; i <= 3; i++) {
      const y = padding.top + (plotH / 3) * i;
      const valLabel = Math.round(maxVal - (maxVal / 3) * i);
      const line = createSvgElement("line");
      line.setAttribute("x1", String(padding.left));
      line.setAttribute("y1", String(y));
      line.setAttribute("x2", String(width - padding.right));
      line.setAttribute("y2", String(y));
      line.setAttribute("stroke", "#e2e8f0");
      line.setAttribute("stroke-dasharray", "3 3");
      gGrid.append(line);

      const text = createSvgElement("text");
      text.setAttribute("x", String(padding.left - 6));
      text.setAttribute("y", String(y + 3));
      text.setAttribute("text-anchor", "end");
      text.setAttribute("fill", "#94a3b8");
      text.setAttribute("font-size", "10");
      text.textContent = String(valLabel);
      gGrid.append(text);
    }
    svg.append(gGrid);

    const step = plotW / Math.max(1, items.length - 1);
    const coords = items.map((it, idx) => ({
      x: padding.left + idx * step,
      y: padding.top + plotH - (it.val / maxVal) * plotH,
      label: it.label,
      val: it.val
    }));

    const areaD = `M ${coords[0].x.toFixed(1)} ${(padding.top + plotH).toFixed(1)} ` +
      coords.map(c => `L ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" ") +
      ` L ${coords[coords.length - 1].x.toFixed(1)} ${(padding.top + plotH).toFixed(1)} Z`;
    const areaPath = createSvgElement("path");
    areaPath.setAttribute("d", areaD);
    areaPath.setAttribute("fill", "rgba(37, 99, 235, 0.1)");
    svg.append(areaPath);

    const lineD = "M " + coords.map(c => `${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" L ");
    const linePath = createSvgElement("path");
    linePath.setAttribute("d", lineD);
    linePath.setAttribute("fill", "none");
    linePath.setAttribute("stroke", "#2563eb");
    linePath.setAttribute("stroke-width", "2.5");
    linePath.setAttribute("stroke-linecap", "round");
    linePath.setAttribute("stroke-linejoin", "round");
    svg.append(linePath);

    coords.forEach(pt => {
      const circle = createSvgElement("circle");
      circle.setAttribute("cx", pt.x.toFixed(1));
      circle.setAttribute("cy", pt.y.toFixed(1));
      circle.setAttribute("r", "4");
      circle.setAttribute("fill", "#ffffff");
      circle.setAttribute("stroke", "#2563eb");
      circle.setAttribute("stroke-width", "2");
      const title = createSvgElement("title");
      title.textContent = `${pt.label}: ${pt.val}`;
      circle.append(title);
      svg.append(circle);

      const label = createSvgElement("text");
      label.setAttribute("x", pt.x.toFixed(1));
      label.setAttribute("y", String(height - padding.bottom + 16));
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("fill", "#64748b");
      label.setAttribute("font-size", "10");
      const short = pt.label.length > 9 ? pt.label.slice(0, 8) + "…" : pt.label;
      label.textContent = short;
      svg.append(label);
    });

  } else {
    const plotW = width - padding.left - padding.right;
    const plotH = height - padding.top - padding.bottom;
    const maxVal = Math.max(...items.map(d => d.val), 1) * 1.15;

    const gGrid = createSvgElement("g");
    for (let i = 0; i <= 3; i++) {
      const y = padding.top + (plotH / 3) * i;
      const valLabel = Math.round(maxVal - (maxVal / 3) * i);
      const line = createSvgElement("line");
      line.setAttribute("x1", String(padding.left));
      line.setAttribute("y1", String(y));
      line.setAttribute("x2", String(width - padding.right));
      line.setAttribute("y2", String(y));
      line.setAttribute("stroke", "#e2e8f0");
      line.setAttribute("stroke-dasharray", "3 3");
      gGrid.append(line);

      const text = createSvgElement("text");
      text.setAttribute("x", String(padding.left - 6));
      text.setAttribute("y", String(y + 3));
      text.setAttribute("text-anchor", "end");
      text.setAttribute("fill", "#94a3b8");
      text.setAttribute("font-size", "10");
      text.textContent = String(valLabel);
      gGrid.append(text);
    }
    svg.append(gGrid);

    const step = plotW / items.length;
    const barWidth = Math.min(42, Math.max(16, step * 0.62));

    items.forEach((it, idx) => {
      const barH = (it.val / maxVal) * plotH;
      const x = padding.left + idx * step + (step - barWidth) / 2;
      const y = padding.top + plotH - barH;
      const c = colors[idx % colors.length];

      const rect = createSvgElement("rect");
      rect.setAttribute("x", x.toFixed(1));
      rect.setAttribute("y", y.toFixed(1));
      rect.setAttribute("width", barWidth.toFixed(1));
      rect.setAttribute("height", Math.max(2, barH).toFixed(1));
      rect.setAttribute("rx", "3");
      rect.setAttribute("fill", c);
      const title = createSvgElement("title");
      title.textContent = `${it.label}: ${it.val}`;
      rect.append(title);
      svg.append(rect);

      const valText = createSvgElement("text");
      valText.setAttribute("x", (x + barWidth / 2).toFixed(1));
      valText.setAttribute("y", Math.max(padding.top - 4, y - 4).toFixed(1));
      valText.setAttribute("text-anchor", "middle");
      valText.setAttribute("fill", "#475569");
      valText.setAttribute("font-size", "10");
      valText.setAttribute("font-weight", "600");
      valText.textContent = String(it.val);
      svg.append(valText);

      const catText = createSvgElement("text");
      catText.setAttribute("x", (x + barWidth / 2).toFixed(1));
      catText.setAttribute("y", String(height - padding.bottom + 16));
      catText.setAttribute("text-anchor", "middle");
      catText.setAttribute("fill", "#64748b");
      catText.setAttribute("font-size", "10");
      const short = it.label.length > 9 ? it.label.slice(0, 8) + "…" : it.label;
      catText.textContent = short;
      svg.append(catText);
    });
  }

  return svg;
}

function renderSummary(summary, transcriptId) {
  stopSummaryTimer();
  if (!summary) return;

  const emptyState = byId("summary-empty-state");
  const contentState = byId("summary-content");
  const indicator = byId("summary-status-indicator");
  const btnGen = byId("btn-generate-summary");
  const btnGenText = byId("btn-generate-summary-text");
  const downloadGroup = byId("summary-download-group");
  const modelBadge = byId("summary-model-badge");

  if (emptyState) emptyState.hidden = true;
  if (contentState) contentState.hidden = false;
  if (indicator) indicator.hidden = true;

  if (btnGen) {
    btnGen.disabled = false;
    const provider = byId("summary-provider-select")?.value || "ollama";
    if (btnGenText) {
      btnGenText.textContent = provider === "chatgpt"
        ? "Regerar com ChatGPT"
        : provider === "antigravity"
        ? "Regerar com Antigravity"
        : "Regerar com Ollama";
    }
  }

  if (modelBadge) {
    const prov = summary.provenance?.provider;
    const isChatGPT = prov === "chatgpt";
    const isAntigravity = prov === "antigravity";
    const provName = isChatGPT ? "ChatGPT" : isAntigravity ? "Antigravity" : "Ollama";
    const modName = summary.provenance?.model_name || (isChatGPT ? "gpt-6-luna" : isAntigravity ? "gemini-3.8-flash-low" : "qwen2.5:3b");
    modelBadge.textContent = `${provName} · ${modName}`;
  }

  const thesisEl = byId("summary-core-thesis");
  if (thesisEl) {
    thesisEl.textContent = summary.executive?.core_thesis || "Síntese dos temas centrais abordados.";
  }

  const parasContainer = byId("summary-executive-paragraphs");
  if (parasContainer) {
    clear(parasContainer);
    const paragraphs = summary.executive?.paragraphs || [];
    if (paragraphs.length === 0) {
      parasContainer.append(element("p", { text: "Nenhum detalhe adicional disponível para o resumo executivo." }));
    } else {
      for (const pText of paragraphs) {
        parasContainer.append(element("p", { text: pText }));
      }
    }
  }

  const spokenEl = byId("summary-spoken-text");
  if (spokenEl) {
    spokenEl.textContent = summary.spoken_summary || "";
  }

  const glossaryBody = byId("summary-glossary-body");
  const glossaryCount = byId("glossary-count");
  if (glossaryBody) {
    clear(glossaryBody);
    const items = summary.glossary || [];
    if (glossaryCount) {
      glossaryCount.textContent = `${items.length} ${items.length === 1 ? "termo" : "termos"}`;
    }
    if (items.length === 0) {
      glossaryBody.append(
        element("tr", {}, [
          element("td", { text: "Nenhum termo técnico específico destacado.", attributes: { colspan: "3" } }),
        ])
      );
    } else {
      for (const entry of items) {
        const seekBtn = element("button", {
          className: "timestamp-button",
          text: entry.first_timestamp || "00:00:00",
          type: "button",
          title: `Ir para ${entry.first_timestamp || "00:00:00"}`,
        });
        seekBtn.addEventListener("click", () => {
          seekActivePlayer(parseTimestampSeconds(entry.first_timestamp));
        });

        glossaryBody.append(
          element("tr", {}, [
            element("td", {}, [seekBtn]),
            element("td", { className: "col-term", text: entry.term }),
            element("td", { className: "col-definition", text: entry.definition }),
          ])
        );
      }
    }
  }

  const chartsGrid = byId("summary-charts-grid");
  const chartsCount = byId("charts-count");
  if (chartsGrid) {
    clear(chartsGrid);
    const charts = summary.charts || [];
    if (chartsCount) {
      chartsCount.textContent = `${charts.length} ${charts.length === 1 ? "gráfico" : "gráficos"}`;
    }
    if (charts.length === 0) {
      chartsGrid.append(
        element("div", { className: "charts-empty-placeholder" }, [
          element("p", { text: "Nenhum gráfico estruturado automaticamente neste resumo." })
        ])
      );
    } else {
      charts.forEach((chart, idx) => {
        const typeBadge = element("span", {
          className: "chart-type-badge",
          text: chart.chart_type ? `AntV · ${(chart.chart_type).toUpperCase()}` : "AntV · CHART",
        });
        const tsBtn = element("button", {
          className: "timestamp-button",
          text: chart.timestamp || "00:00:00",
          type: "button",
          title: `Ir para ${chart.timestamp || "00:00:00"}`,
        });
        tsBtn.addEventListener("click", () => {
          seekActivePlayer(parseTimestampSeconds(chart.timestamp));
        });

        const header = element("div", { className: "chart-card-header" }, [
          element("div", { className: "chart-title-group" }, [
            element("h5", { className: "chart-title", text: chart.title || `Visualização #${idx + 1}` }),
            typeBadge,
          ]),
          tsBtn,
        ]);

        const desc = element("p", { className: "chart-description", text: chart.description || "" });

        const chartWrap = element("div", { className: "chart-render-wrap" });
        chartWrap.append(createSvgChart(chart));

        const toggleSpecBtn = element("button", {
          className: "button button-quiet button-sm chart-toggle-spec",
          type: "button",
          text: "Ver especificação AntV",
        });
        const specBox = element("pre", {
          className: "chart-spec-box",
          hidden: true,
          text: JSON.stringify({ type: chart.chart_type || "column", data: chart.data }, null, 2),
        });
        toggleSpecBtn.addEventListener("click", () => {
          specBox.hidden = !specBox.hidden;
          toggleSpecBtn.textContent = specBox.hidden ? "Ver especificação AntV" : "Ocultar especificação";
        });

        const footer = element("div", { className: "chart-card-footer" }, [toggleSpecBtn, specBox]);

        const card = element("article", {
          className: "chart-card",
          attributes: { role: "listitem" },
        }, [header, desc, chartWrap, footer]);

        chartsGrid.append(card);
      });
    }
  }

  // Backwards compatibility for existing flashcards in loaded summaries
  const flashcardsGrid = byId("summary-flashcards-grid");
  const flashcardsCount = byId("flashcards-count");
  if (flashcardsGrid) {
    clear(flashcardsGrid);
    const cards = summary.flashcards || [];
    if (flashcardsCount) {
      flashcardsCount.textContent = `${cards.length} ${cards.length === 1 ? "card" : "cards"}`;
    }
    cards.forEach((card, idx) => {
      const idxSpan = element("span", {
        className: "flashcard-idx",
        text: `Card #${String(idx + 1).padStart(2, "0")}`,
      });
      const tsBtn = element("button", {
        className: "timestamp-button",
        text: card.timestamp || "00:00:00",
        type: "button",
        title: `Ouvir trecho (${card.timestamp || "00:00:00"})`,
      });
      tsBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        seekActivePlayer(parseTimestampSeconds(card.timestamp));
      });

      const header = element("div", { className: "flashcard-header" }, [idxSpan, tsBtn]);
      const questionEl = element("h5", { className: "flashcard-question", text: card.question });
      const answerEl = element("div", {
        className: "flashcard-answer",
        text: card.answer,
        attributes: { id: `flashcard-ans-${idx}` },
      });

      const toggleBtn = element("button", {
        className: "button button-secondary button-sm flashcard-toggle",
        text: "Revelar Resposta",
        type: "button",
        attributes: {
          "aria-expanded": "false",
          "aria-controls": `flashcard-ans-${idx}`,
        },
      });

      const cardEl = element("article", {
        className: "flashcard",
        attributes: { role: "listitem" },
      }, [
        header,
        questionEl,
        answerEl,
        element("div", { className: "flashcard-footer" }, [toggleBtn]),
      ]);

      const toggleCard = () => {
        const isRevealed = cardEl.classList.toggle("is-revealed");
        toggleBtn.setAttribute("aria-expanded", String(isRevealed));
        toggleBtn.textContent = isRevealed ? "Ocultar Resposta" : "Revelar Resposta";
      };

      toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleCard();
      });
      cardEl.addEventListener("click", toggleCard);

      flashcardsGrid.append(cardEl);
    });
  }

  if (downloadGroup) {
    downloadGroup.hidden = false;
    const btnMd = byId("btn-download-summary-md");
    const btnJson = byId("btn-download-summary-json");
    if (btnMd) {
      btnMd.href = api.summaryDownloadUrl(transcriptId, "md");
      btnMd.download = `resumo_${transcriptId}.md`;
    }
    if (btnJson) {
      btnJson.href = api.summaryDownloadUrl(transcriptId, "json");
      btnJson.download = `resumo_${transcriptId}.json`;
    }
  }
}

async function loadSummary(transcriptId, signal) {
  resetSummaryUI();
  try {
    const summary = await api.summary(transcriptId, { signal });
    if (state.readerContext?.transcriptId === transcriptId && summary && summary.executive) {
      renderSummary(summary, transcriptId);
    }
  } catch (_error) {
    // 404 esperado quando o resumo ainda não foi gerado
  }
}

async function refreshChatGPTStatus() {
  const authBar = byId("chatgpt-auth-bar");
  const authStatus = byId("chatgpt-auth-status");
  const btnConnect = byId("btn-chatgpt-connect");
  const btnDisconnect = byId("btn-chatgpt-disconnect");
  const consentNotice = byId("chatgpt-consent-notice");
  const antigravityBar = byId("antigravity-auth-bar");
  const antigravityNotice = byId("antigravity-consent-notice");
  const providerSelect = byId("summary-provider-select");
  const btnGenText = byId("btn-generate-summary-text");

  const provider = providerSelect?.value || "ollama";
  const isChatGPT = provider === "chatgpt";
  const isAntigravity = provider === "antigravity";

  if (authBar) authBar.hidden = !isChatGPT;
  if (consentNotice) consentNotice.hidden = !isChatGPT;
  if (antigravityBar) antigravityBar.hidden = !isAntigravity;
  if (antigravityNotice) antigravityNotice.hidden = !isAntigravity;

  if (btnGenText) {
    btnGenText.textContent = isChatGPT
      ? "Gerar Resumo com ChatGPT"
      : isAntigravity
      ? "Gerar Resumo com Antigravity"
      : "Gerar Resumo com Ollama";
  }

  if (!isChatGPT) return;

  try {
    const status = await api.chatgptStatus();
    state.chatgptStatus = status;
    if (status.connected) {
      if (authStatus) {
        authStatus.textContent = `${status.email || "Conectado"} (${status.model || "gpt-6-luna"})`;
      }
      if (btnConnect) btnConnect.hidden = true;
      if (btnDisconnect) btnDisconnect.hidden = false;
    } else {
      if (authStatus) {
        authStatus.textContent = "Não conectado";
      }
      if (btnConnect) btnConnect.hidden = false;
      if (btnDisconnect) btnDisconnect.hidden = true;
    }
  } catch (_e) {
    if (authStatus) authStatus.textContent = "Offline";
  }
}

async function handleChatGPTConnect() {
  try {
    const res = await api.chatgptLogin();
    if (res && res.auth_url) {
      const popup = window.open(res.auth_url, "chatgpt-oauth", "width=600,height=750");
      toast("Janela de login do ChatGPT aberta.");
      const interval = setInterval(async () => {
        if (!popup || popup.closed) {
          clearInterval(interval);
          await refreshChatGPTStatus();
        }
      }, 1000);
    }
  } catch (err) {
    toast(`Falha ao iniciar autenticação: ${errorMessage(err)}`, "error");
  }
}

async function handleChatGPTDisconnect() {
  try {
    await api.chatgptLogout();
    state.chatgptStatus = null;
    toast("Desconectado do ChatGPT.");
    await refreshChatGPTStatus();
  } catch (err) {
    toast(`Falha ao desconectar: ${errorMessage(err)}`, "error");
  }
}

async function handleGenerateSummary() {
  const transcriptId = state.readerContext?.transcriptId;
  if (!transcriptId) {
    toast("Nenhuma transcrição ativa selecionada.", "error");
    return;
  }

  const provider = byId("summary-provider-select")?.value || "ollama";
  if (provider === "chatgpt" && !state.chatgptStatus?.connected) {
    toast("Por favor, conecte sua conta ChatGPT antes de gerar a síntese.", "error");
    return;
  }

  const btnGen = byId("btn-generate-summary");
  const btnGenText = byId("btn-generate-summary-text");
  const indicator = byId("summary-status-indicator");
  const progressBar = byId("summary-progress-bar");
  const progressPercent = byId("summary-progress-percent");
  const statusText = byId("summary-status-text");

  if (btnGen) btnGen.disabled = true;
  if (btnGenText) btnGenText.textContent = "Gerando síntese...";
  if (indicator) {
    indicator.hidden = false;
    indicator.classList.remove("is-error");
  }
  if (progressBar) {
    progressBar.style.width = "0%";
    progressBar.setAttribute("aria-valuenow", "0");
    progressBar.classList.remove("is-complete");
  }
  if (progressPercent) progressPercent.textContent = "0%";
  if (statusText) {
    statusText.textContent = provider === "chatgpt"
      ? "Iniciando síntese via ChatGPT (gpt-6-luna)…"
      : provider === "antigravity"
      ? "Iniciando síntese via Antigravity (Gemini 3.8 Flash)…"
      : "Iniciando síntese via Ollama…";
  }

  startSummaryTimer();
  announce(
    provider === "chatgpt"
      ? "Iniciando síntese com ChatGPT."
      : provider === "antigravity"
      ? "Iniciando síntese com Antigravity."
      : "Iniciando síntese estruturada com Ollama."
  );

  let receivedSummary = null;

  const onProgress = (event) => {
    if (state.readerContext?.transcriptId !== transcriptId) {
      return;
    }
    const { event: eventName, data } = event;
    if (eventName === "complete" || (data && (data.status === "complete" || data.executive))) {
      receivedSummary = data?.summary || (data?.executive ? data : null);
      updateSummaryProgress(100, "Síntese concluída!");
      return;
    }
    if (eventName === "error") {
      const detail = data?.detail || data?.error || data?.message || "Falha durante o processamento do modelo.";
      throw new ApiError(detail);
    }

    let percent = null;
    if (typeof data?.progress_percent === "number") {
      percent = data.progress_percent;
    } else if (typeof data?.percent === "number") {
      percent = data.percent;
    } else if (typeof data?.chunk_current === "number" && typeof data?.chunk_total === "number" && data.chunk_total > 0) {
      percent = 10 + Math.round((data.chunk_current / data.chunk_total) * 70);
    }

    const msg = data?.message || data?.text || data?.phase;
    updateSummaryProgress(percent, msg);
  };

  try {
    const payload = {
      provider,
      model_name: provider === "chatgpt"
        ? "gpt-6-luna"
        : provider === "antigravity"
        ? "gemini-3.8-flash-low"
        : undefined,
    };
    const streamResult = await api.streamSummary(transcriptId, onProgress, { payload });
    const summaryToRender = receivedSummary || streamResult;

    stopSummaryTimer();

    let finalSummary = summaryToRender;
    if (!finalSummary || !finalSummary.executive) {
      finalSummary = await api.summary(transcriptId);
    }

    if (state.readerContext?.transcriptId === transcriptId && finalSummary) {
      renderSummary(finalSummary, transcriptId);
    }

    toast("Resumo estruturado gerado com sucesso!");
    announce("Resumo estruturado concluído.");
  } catch (error) {
    stopSummaryTimer();
    const msg = errorMessage(error);
    toast(msg, "error");

    if (indicator) {
      indicator.classList.add("is-error");
      indicator.hidden = false;
    }
    if (statusText) {
      statusText.textContent = `Falha: ${msg}`;
    }
    if (progressPercent) {
      progressPercent.textContent = "Erro";
    }
    if (progressBar) {
      progressBar.style.width = "100%";
      progressBar.classList.remove("is-complete");
    }

    if (btnGen) btnGen.disabled = false;
    if (btnGenText) {
      btnGenText.textContent = provider === "chatgpt"
        ? "Tentar Novamente com ChatGPT"
        : provider === "antigravity"
        ? "Tentar Novamente com Antigravity"
        : "Tentar Novamente com Ollama";
    }
  }
}

function wireStaticEvents() {
  window.addEventListener("local-api-offline", () => setServiceState(false));
  window.addEventListener("local-api-online", () => {
    if (state.health) {
      setServiceState(true);
    }
  });
  window.addEventListener("offline", () => setServiceState(false));
  window.addEventListener("online", loadAll);
  for (const link of document.querySelectorAll("[data-view], [data-view-link]")) {
    link.addEventListener("click", (event) => {
      const target = event.currentTarget.dataset.view || event.currentTarget.dataset.viewLink;
      event.preventDefault();
      showView(target, true);
    });
  }
  window.addEventListener("hashchange", () => showView(window.location.hash.slice(1)));
  for (const button of document.querySelectorAll("[data-close-dialog]")) {
    button.addEventListener("click", () => byId(button.dataset.closeDialog).close());
  }

  byId("btn-generate-summary")?.addEventListener("click", handleGenerateSummary);
  byId("summary-provider-select")?.addEventListener("change", refreshChatGPTStatus);
  byId("btn-chatgpt-connect")?.addEventListener("click", handleChatGPTConnect);
  byId("btn-chatgpt-disconnect")?.addEventListener("click", handleChatGPTDisconnect);
  window.addEventListener("message", (e) => {
    if (e.data === "chatgpt-connected") {
      refreshChatGPTStatus();
    }
  });
  byId("btn-copy-spoken")?.addEventListener("click", async () => {
    const spokenEl = byId("summary-spoken-text");
    const text = spokenEl?.textContent || "";
    if (!text) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      toast("Roteiro falado copiado para a área de transferência.");
    } catch (_e) {
      toast("Não foi possível copiar para a área de transferência.", "error");
    }
  });

  document.querySelectorAll("[data-reader-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-reader-tab]").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      const mode = btn.dataset.readerTab;
      const summarySec = byId("summary-section");
      const readerLayout = byId("reader-layout");
      const chartsSub = summarySec?.querySelector('[aria-labelledby="charts-title"]');
      if (mode === "transcription") {
        if (summarySec) summarySec.hidden = true;
        if (readerLayout) readerLayout.hidden = false;
      } else if (mode === "summary") {
        if (summarySec) summarySec.hidden = false;
        if (readerLayout) readerLayout.hidden = true;
        if (chartsSub) chartsSub.hidden = true;
      } else if (mode === "charts") {
        if (summarySec) summarySec.hidden = false;
        if (readerLayout) readerLayout.hidden = true;
        if (chartsSub) chartsSub.hidden = false;
      } else {
        if (summarySec) summarySec.hidden = false;
        if (readerLayout) readerLayout.hidden = false;
        if (chartsSub) chartsSub.hidden = false;
      }
    });
  });

  byId("retry-connection").addEventListener("click", loadAll);
  byId("refresh-jobs").addEventListener("click", async () => {
    try {
      state.jobs = await api.jobs();
      state.transcripts = await api.transcripts();
      renderAll();
      connectActiveJobs();
      announce("Fila atualizada.");
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  });

  byId("subject-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = byId("subject-name");
    if (!input.reportValidity()) {
      return;
    }
    try {
      const subject = await api.createSubject(input.value.trim());
      state.subjects.push(subject);
      state.subjects.sort((left, right) => left.name.localeCompare(right.name, "pt-BR"));
      input.value = "";
      renderSubjects();
      renderDashboard();
      toast("Matéria criada.");
      input.focus();
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  });

  byId("upload-file").addEventListener("change", () => {
    const file = byId("upload-file").files[0];
    const title = byId("upload-title");
    if (file && !title.value) {
      title.value = file.name.replace(/\.[^.]+$/, "");
    }
  });

  byId("upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) {
      return;
    }
    const file = byId("upload-file").files[0];
    if (!file) {
      toast("Selecione um arquivo de mídia.", "error");
      return;
    }
    if (state.capabilities && file.size > state.capabilities.upload_max_bytes) {
      toast(`O arquivo ultrapassa o limite de ${formatBytes(state.capabilities.upload_max_bytes)}.`, "error");
      return;
    }
    const submit = byId("upload-submit");
    const progress = byId("upload-progress");
    submit.disabled = true;
    progress.hidden = false;
    byId("upload-status").textContent = "Validando e importando no armazenamento local…";
    try {
      const data = new FormData(form);
      const recording = await api.uploadRecording(data);
      state.recordings.unshift(recording);
      form.reset();
      byId("upload-date").value = localDateValue();
      state.searchResults = null;
      renderSubjects();
      renderRecordings();
      byId("upload-status").textContent = "Importação concluída.";
      toast("Gravação importada com segurança.");
      announce(`${recording.title} foi adicionada à biblioteca.`);
    } catch (error) {
      byId("upload-status").textContent = "A importação não foi concluída.";
      toast(errorMessage(error), "error");
    } finally {
      submit.disabled = state.subjects.length === 0;
      progress.hidden = true;
    }
  });

  byId("search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = byId("search-query").value.trim();
    if (!query) {
      searchRequest.invalidate();
      state.searchResults = null;
      renderRecordings();
      return;
    }
    const request = searchRequest.begin(query);
    try {
      const results = await api.search(query, { signal: request.signal });
      if (
        !searchRequest.isCurrent(request, query) ||
        byId("search-query").value.trim() !== query
      ) {
        return;
      }
      state.searchResults = results;
      renderRecordings();
    } catch (error) {
      if (searchRequest.isCurrent(request, query) && !isAbortError(error)) {
        toast(errorMessage(error), "error");
      }
    }
  });
  byId("search-query").addEventListener("search", () => {
    if (!byId("search-query").value) {
      searchRequest.invalidate();
      state.searchResults = null;
      renderRecordings();
    }
  });
  byId("subject-filter").addEventListener("change", renderRecordings);

  byId("transcription-model").addEventListener("change", updateTranscriptionWarning);
  byId("transcription-profile").addEventListener("change", updateTranscriptionWarning);
  byId("transcription-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!event.currentTarget.reportValidity()) {
      return;
    }
    try {
      state.pendingJob = buildPendingJob();
      renderTranscriptionSummary(state.pendingJob);
      byId("transcription-dialog").close();
      byId("confirm-dialog").showModal();
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  });
  byId("cancel-enqueue").addEventListener("click", () => {
    byId("confirm-dialog").close();
    byId("transcription-dialog").showModal();
  });
  byId("confirm-enqueue").addEventListener("click", async () => {
    if (!state.pendingJob) {
      return;
    }
    const button = byId("confirm-enqueue");
    button.disabled = true;
    try {
      const job = await api.createJob(state.pendingJob.payload);
      replaceJob(job);
      state.pendingJob = null;
      byId("confirm-dialog").close();
      renderAll();
      connectActiveJobs();
      showView("fila", true);
      toast("Transcrição enfileirada.");
      announce("Transcrição enfileirada e acompanhamento por eventos iniciado.");
    } catch (error) {
      toast(errorMessage(error), "error");
    } finally {
      button.disabled = false;
    }
  });

  byId("cancel-delete").addEventListener("click", () => byId("delete-dialog").close());
  byId("confirm-delete").addEventListener("click", async () => {
    const recording = state.pendingDelete;
    if (!recording) {
      return;
    }
    const button = byId("confirm-delete");
    button.disabled = true;
    try {
      await api.deleteRecording(recording.id);
      state.recordings = state.recordings.filter((item) => item.id !== recording.id);
      state.jobs = state.jobs.filter((job) => job.recording_id !== recording.id);
      state.transcripts = state.transcripts.filter((item) => item.recording_id !== recording.id);
      state.pendingDelete = null;
      byId("delete-dialog").close();
      renderAll();
      connectActiveJobs();
      toast("Gravação excluída.");
    } catch (error) {
      toast(errorMessage(error), "error");
    } finally {
      button.disabled = false;
    }
  });
}

function localDateValue() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

async function start() {
  wireStaticEvents();
  byId("upload-date").value = localDateValue();
  showView(window.location.hash.slice(1));
  await loadAll();
}

start();
