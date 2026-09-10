import { ApiError, LocalApi } from "/assets/api.js";
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
  activeStreams: new Map(),
  streamStates: new Map(),
};

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
  return error instanceof ApiError ? error.message : "Ocorreu um erro inesperado.";
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

function replaceJob(job) {
  const index = state.jobs.findIndex((item) => item.id === job.id);
  if (index === -1) {
    state.jobs.unshift(job);
  } else {
    state.jobs[index] = job;
  }
  state.jobs.sort((left, right) => right.created_at.localeCompare(left.created_at));
}

async function loadAll() {
  setServiceLoading();
  const tasks = await Promise.allSettled([
    api.health(),
    api.capabilities(),
    api.runtime(),
    api.models(),
    api.subjects(),
    api.recordings(),
    api.jobs(),
    api.transcripts(),
  ]);
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
  state.jobs = jobs.status === "fulfilled" ? jobs.value : [];
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
  const activeIds = new Set(
    state.jobs.filter((job) => ["pending", "running"].includes(job.status)).map((job) => job.id),
  );
  for (const [jobId, close] of state.activeStreams.entries()) {
    if (!activeIds.has(jobId)) {
      close();
      state.activeStreams.delete(jobId);
      state.streamStates.delete(jobId);
    }
  }
  for (const jobId of activeIds) {
    if (state.activeStreams.has(jobId)) {
      continue;
    }
    state.streamStates.set(jobId, "connecting");
    const close = api.eventStream(jobId, {
      open: () => {
        state.streamStates.set(jobId, "connected");
        renderStreamState();
      },
      error: () => {
        state.streamStates.set(jobId, "reconnecting");
        renderStreamState();
      },
      invalid: () => toast("Um evento de progresso inválido foi ignorado.", "error"),
      message: (event) => updateJobFromEvent(jobId, event),
    });
    state.activeStreams.set(jobId, close);
  }
  renderStreamState();
}

async function updateJobFromEvent(jobId, event) {
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
  });
  renderJobs();
  renderDashboard();
  renderRecordings();
  announce(`${recordingFor(current.recording_id)?.title || "Transcrição"}: ${phaseLabel(event.phase)}, ${formatPercent(event.percent)}.`);
  if (["succeeded", "failed", "cancelled"].includes(event.status)) {
    try {
      replaceJob(await api.job(jobId));
      state.transcripts = await api.transcripts();
    } catch (error) {
      toast(errorMessage(error), "error");
    }
    const close = state.activeStreams.get(jobId);
    close?.();
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
  try {
    const transcripts = await api.transcripts(recordingId);
    if (transcripts.length === 0) {
      throw new ApiError("Esta gravação ainda não possui transcrição concluída.");
    }
    state.selectedRecording = recording;
    renderReader(recording, transcripts[0], await api.exports(transcripts[0].id));
    showView("leitura", true);
  } catch (error) {
    toast(errorMessage(error), "error");
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
    seek.addEventListener("click", () => {
      player.currentTime = segment.start_seconds;
      player.focus();
      player.play().catch(() => undefined);
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
    segments.append(element("li", {}, [seek, copy]));
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
  button.disabled = true;
  try {
    const artifact = await api.createExport(transcriptId, format);
    const artifacts = await api.exports(transcriptId);
    renderExports(transcriptId, artifacts);
    toast(`${exportLabels[format]} gerado. O download será iniciado.`);
    const download = element("a", {
      href: `/api/exports/${encodeURIComponent(artifact.id)}`,
      attributes: { download: `transcricao.${format}` },
    });
    document.body.append(download);
    download.click();
    download.remove();
  } catch (error) {
    toast(errorMessage(error), "error");
    button.disabled = false;
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
      state.searchResults = null;
      renderRecordings();
      return;
    }
    try {
      state.searchResults = await api.search(query);
      renderRecordings();
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  });
  byId("search-query").addEventListener("search", () => {
    if (!byId("search-query").value) {
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
