import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function importSource(relativePath) {
  const source = await readFile(new URL(relativePath, import.meta.url), "utf8");
  return import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
}

const { JobEventTracker, LatestRequest, isAbortError } = await importSource(
  "../src/local_transcriber/web/async_state.js",
);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

async function applyLatest(scope, context, controlled, apply, errors = []) {
  const token = scope.begin(context);
  try {
    const value = await controlled.promise;
    if (scope.isCurrent(token, context)) {
      apply(value);
    }
  } catch (error) {
    if (scope.isCurrent(token, context) && !isAbortError(error)) {
      errors.push(error.message);
    }
  }
}

test("leitura A lenta não substitui leitura B rápida", async () => {
  const scope = new LatestRequest();
  const slowA = deferred();
  const fastB = deferred();
  let visible = null;

  const loadA = applyLatest(scope, "A", slowA, (value) => {
    visible = value;
  });
  const loadB = applyLatest(scope, "B", fastB, (value) => {
    visible = value;
  });
  fastB.resolve("leitura B");
  await loadB;
  slowA.resolve("leitura A");
  await loadA;

  assert.equal(visible, "leitura B");
});

test("pesquisa A lenta não substitui pesquisa B rápida", async () => {
  const scope = new LatestRequest();
  const slowA = deferred();
  const fastB = deferred();
  let results = [];

  const searchA = applyLatest(scope, "termo A", slowA, (value) => {
    results = value;
  });
  const searchB = applyLatest(scope, "termo B", fastB, (value) => {
    results = value;
  });
  fastB.resolve(["resultado B"]);
  await searchB;
  slowA.resolve(["resultado A"]);
  await searchA;

  assert.deepEqual(results, ["resultado B"]);
});

test("exportação antiga não substitui controles da nova leitura", async () => {
  const readerScope = new LatestRequest();
  const exportScope = new LatestRequest();
  const exportA = deferred();
  const readerA = readerScope.begin("transcript-A");
  const exportToken = exportScope.begin("transcript-A:txt", { abortPrevious: false });
  let controls = "controles B";
  const downloads = [];

  const finishExport = (async () => {
    const artifact = await exportA.promise;
    if (!exportScope.isCurrent(exportToken, "transcript-A:txt")) {
      return;
    }
    downloads.push(artifact.id);
    if (readerScope.isCurrent(readerA, "transcript-A")) {
      controls = "controles A";
    }
  })();

  readerScope.begin("transcript-B");
  exportA.resolve({ id: "artifact-A" });
  await finishExport;

  assert.equal(controls, "controles B");
  assert.deepEqual(downloads, ["artifact-A"]);
});

test("duas cargas globais fora de ordem preservam a mais recente", async () => {
  const scope = new LatestRequest();
  const oldLoad = deferred();
  const recentLoad = deferred();
  let snapshot = null;

  const first = applyLatest(scope, "global", oldLoad, (value) => {
    snapshot = value;
  });
  const second = applyLatest(scope, "global", recentLoad, (value) => {
    snapshot = value;
  });
  recentLoad.resolve({ revision: 2 });
  await second;
  oldLoad.resolve({ revision: 1 });
  await first;

  assert.deepEqual(snapshot, { revision: 2 });
});

test("falha de seleção obsoleta não aparece no contexto atual", async () => {
  const scope = new LatestRequest();
  const oldLoad = deferred();
  const currentLoad = deferred();
  const errors = [];

  const first = applyLatest(scope, "A", oldLoad, () => undefined, errors);
  const second = applyLatest(scope, "B", currentLoad, () => undefined, errors);
  currentLoad.resolve("B");
  await second;
  oldLoad.reject(new Error("falha A"));
  await first;

  assert.deepEqual(errors, []);
});

test("evento SSE duplicado é rejeitado", () => {
  const tracker = new JobEventTracker();
  const stream = tracker.begin("job-A", 0);

  assert.equal(tracker.accept(stream, "1", 1), true);
  assert.equal(tracker.accept(stream, "1", 1), false);
  assert.equal(tracker.lastSequence("job-A"), 1);
});

test("evento SSE fora de ordem é rejeitado", () => {
  const tracker = new JobEventTracker();
  const stream = tracker.begin("job-A", 0);

  assert.equal(tracker.accept(stream, "2", 2), true);
  assert.equal(tracker.accept(stream, "1", 1), false);
  assert.equal(tracker.lastSequence("job-A"), 2);
});

test("replay inicial anterior ao snapshot não causa regressão", () => {
  const tracker = new JobEventTracker();
  const stream = tracker.begin("job-A", 7);

  assert.equal(tracker.cursor(stream), 7);
  assert.equal(tracker.accept(stream, "3", 3), false);
  assert.equal(tracker.accept(stream, "7", 7), false);
  assert.equal(tracker.accept(stream, "8", 8), true);
  assert.equal(tracker.lastSequence("job-A"), 8);
});

test("reconexão parte da última sequência aceita", () => {
  const tracker = new JobEventTracker();
  const first = tracker.begin("job-A", 3);
  assert.equal(tracker.accept(first, "4", 4), true);
  tracker.stop(first);

  const reconnected = tracker.begin("job-A", 3);
  assert.equal(tracker.cursor(reconnected), 4);
  assert.equal(tracker.accept(reconnected, "4", 4), false);
  assert.equal(tracker.accept(reconnected, "5", 5), true);
});

test("callback tardio de listener encerrado é descartado", async () => {
  class FakeEventSource {
    static latest = null;

    constructor(url) {
      this.url = url;
      this.listeners = new Map();
      FakeEventSource.latest = this;
    }

    addEventListener(name, callback) {
      this.listeners.set(name, callback);
    }

    close() {}

    emit(name, event) {
      this.listeners.get(name)?.(event);
    }
  }

  globalThis.EventSource = FakeEventSource;
  globalThis.window = new EventTarget();
  const { LocalApi } = await importSource("../src/local_transcriber/web/api.js");
  const received = [];
  const close = new LocalApi().eventStream(
    "job A",
    { message: (event) => received.push(event) },
    { afterSequence: 4 },
  );
  const source = FakeEventSource.latest;
  assert.equal(source.url, "/api/jobs/job%20A/events?after_sequence=4");

  close();
  source.emit("progress", {
    data: JSON.stringify({ job_id: "job A", sequence: 5 }),
    lastEventId: "5",
  });

  assert.deepEqual(received, []);
});

test("jobs simultâneos mantêm sequências independentes", () => {
  const tracker = new JobEventTracker();
  const jobA = tracker.begin("job-A", 2);
  const jobB = tracker.begin("job-B", 10);

  assert.equal(tracker.accept(jobA, "3", 3), true);
  assert.equal(tracker.accept(jobB, "11", 11), true);
  assert.equal(tracker.accept(jobA, "3", 3), false);
  assert.equal(tracker.lastSequence("job-A"), 3);
  assert.equal(tracker.lastSequence("job-B"), 11);

  tracker.retain(new Set(["job-B"]));
  assert.equal(tracker.lastSequence("job-A"), 0);
  assert.equal(tracker.lastSequence("job-B"), 11);
});
