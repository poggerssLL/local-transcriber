export function isAbortError(error) {
  return Boolean(error && typeof error === "object" && error.name === "AbortError");
}

export class LatestRequest {
  constructor() {
    this.generation = 0;
    this.controller = null;
  }

  begin(context, { abortPrevious = true, abortable = true } = {}) {
    if (abortPrevious) {
      this.controller?.abort();
    }
    this.generation += 1;
    this.controller = abortable ? new AbortController() : null;
    return Object.freeze({
      context,
      generation: this.generation,
      signal: this.controller?.signal,
    });
  }

  isCurrent(token, context = token.context) {
    return (
      token.generation === this.generation &&
      Object.is(token.context, context) &&
      token.signal?.aborted !== true
    );
  }

  invalidate() {
    this.controller?.abort();
    this.controller = null;
    this.generation += 1;
  }
}

function sequenceNumber(value) {
  if (typeof value === "string" && value.trim() === "") {
    return null;
  }
  const sequence = Number(value);
  return Number.isSafeInteger(sequence) && sequence >= 0 ? sequence : null;
}

export class JobEventTracker {
  constructor() {
    this.jobs = new Map();
  }

  seed(jobId, sequence) {
    const candidate = sequenceNumber(sequence);
    if (candidate === null) {
      return this.lastSequence(jobId);
    }
    const current = this.jobs.get(jobId);
    if (!current) {
      this.jobs.set(jobId, { active: false, generation: 0, sequence: candidate });
    } else if (candidate > current.sequence) {
      current.sequence = candidate;
    }
    return this.lastSequence(jobId);
  }

  begin(jobId, snapshotSequence = 0) {
    this.seed(jobId, snapshotSequence);
    const current = this.jobs.get(jobId) || { active: false, generation: 0, sequence: 0 };
    const entry = {
      active: true,
      generation: current.generation + 1,
      sequence: current.sequence,
    };
    this.jobs.set(jobId, entry);
    return Object.freeze({ jobId, generation: entry.generation });
  }

  isCurrent(token) {
    const current = this.jobs.get(token.jobId);
    return current?.active === true && current.generation === token.generation;
  }

  cursor(token) {
    return this.isCurrent(token) ? this.jobs.get(token.jobId).sequence : null;
  }

  accept(token, eventId, payloadSequence) {
    if (!this.isCurrent(token)) {
      return false;
    }
    const id = sequenceNumber(eventId);
    const payload = sequenceNumber(payloadSequence);
    if (id === null || id === 0 || payload === null || id !== payload) {
      return false;
    }
    const current = this.jobs.get(token.jobId);
    if (id <= current.sequence) {
      return false;
    }
    current.sequence = id;
    return true;
  }

  stop(token, { clear = false } = {}) {
    if (!this.isCurrent(token)) {
      return false;
    }
    if (clear) {
      this.jobs.delete(token.jobId);
    } else {
      const current = this.jobs.get(token.jobId);
      current.active = false;
      current.generation += 1;
    }
    return true;
  }

  lastSequence(jobId) {
    return this.jobs.get(jobId)?.sequence || 0;
  }

  retain(jobIds) {
    for (const jobId of this.jobs.keys()) {
      if (!jobIds.has(jobId)) {
        this.jobs.delete(jobId);
      }
    }
  }
}
