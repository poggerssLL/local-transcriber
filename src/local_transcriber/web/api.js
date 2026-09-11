const API_ROOT = "/api";

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readError(response) {
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (Array.isArray(payload.detail)) {
      return payload.detail.map((item) => item.message || "Campo inválido").join("; ");
    }
  } catch (_error) {
    // A mensagem genérica abaixo não expõe uma resposta inesperada do servidor.
  }
  return `A operação falhou (${response.status}).`;
}

export class LocalApi {
  async request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    if (options.body && !(options.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    let response;
    try {
      response = await fetch(`${API_ROOT}${path}`, {
        ...options,
        headers,
        credentials: "same-origin",
      });
    } catch (error) {
      if (error && typeof error === "object" && error.name === "AbortError") {
        throw error;
      }
      window.dispatchEvent(new Event("local-api-offline"));
      throw new ApiError("Não foi possível acessar o serviço local.");
    }
    window.dispatchEvent(new Event("local-api-online"));
    if (!response.ok) {
      throw new ApiError(await readError(response), response.status);
    }
    if (response.status === 204) {
      return null;
    }
    return response.json();
  }

  health(options = {}) {
    return this.request("/health", options);
  }

  capabilities(options = {}) {
    return this.request("/capabilities", options);
  }

  runtime(options = {}) {
    return this.request("/runtime", options);
  }

  models(options = {}) {
    return this.request("/models", options);
  }

  subjects(options = {}) {
    return this.request("/subjects", options);
  }

  createSubject(name) {
    return this.request("/subjects", { method: "POST", body: JSON.stringify({ name }) });
  }

  recordings(subjectId = "", options = {}) {
    const query = subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : "";
    return this.request(`/recordings${query}`, options);
  }

  uploadRecording(formData) {
    return this.request("/recordings", { method: "POST", body: formData });
  }

  deleteRecording(recordingId) {
    return this.request(`/recordings/${encodeURIComponent(recordingId)}`, { method: "DELETE" });
  }

  search(query, options = {}) {
    return this.request(`/search?q=${encodeURIComponent(query)}`, options);
  }

  jobs(options = {}) {
    return this.request("/jobs", options);
  }

  job(jobId, options = {}) {
    return this.request(`/jobs/${encodeURIComponent(jobId)}`, options);
  }

  createJob(payload) {
    return this.request("/jobs", { method: "POST", body: JSON.stringify(payload) });
  }

  cancelJob(jobId) {
    return this.request(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  }

  retryJob(jobId) {
    return this.request(`/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
  }

  transcripts(recordingId = "", options = {}) {
    const query = recordingId ? `?recording_id=${encodeURIComponent(recordingId)}` : "";
    return this.request(`/transcripts${query}`, options);
  }

  transcript(transcriptId, options = {}) {
    return this.request(`/transcripts/${encodeURIComponent(transcriptId)}`, options);
  }

  exports(transcriptId, options = {}) {
    return this.request(`/transcripts/${encodeURIComponent(transcriptId)}/exports`, options);
  }

  createExport(transcriptId, format) {
    return this.request(`/transcripts/${encodeURIComponent(transcriptId)}/exports`, {
      method: "POST",
      body: JSON.stringify({ format }),
    });
  }

  eventStream(jobId, handlers, { afterSequence = 0 } = {}) {
    const cursor = Number.isSafeInteger(afterSequence) && afterSequence >= 0 ? afterSequence : 0;
    const source = new EventSource(
      `${API_ROOT}/jobs/${encodeURIComponent(jobId)}/events?after_sequence=${cursor}`,
    );
    let active = true;
    const eventNames = ["state", "phase", "progress", "failure", "cancellation", "completion"];
    for (const eventName of eventNames) {
      source.addEventListener(eventName, (event) => {
        if (!active) {
          return;
        }
        try {
          handlers.message(JSON.parse(event.data), event.lastEventId);
        } catch (_error) {
          handlers.invalid?.();
        }
      });
    }
    source.onopen = () => {
      if (active) {
        handlers.open?.();
      }
    };
    source.onerror = () => {
      if (active) {
        handlers.error?.();
      }
    };
    return () => {
      active = false;
      source.close();
    };
  }
}
