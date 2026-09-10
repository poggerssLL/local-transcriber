export const byId = (id) => document.getElementById(id);

export function clear(node) {
  node.replaceChildren();
  return node;
}

export function element(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) {
    node.className = options.className;
  }
  if (options.text !== undefined) {
    node.textContent = String(options.text);
  }
  if (options.type) {
    node.type = options.type;
  }
  if (options.href) {
    node.href = options.href;
  }
  if (options.title) {
    node.title = options.title;
  }
  if (options.dataset) {
    for (const [name, value] of Object.entries(options.dataset)) {
      node.dataset[name] = String(value);
    }
  }
  if (options.attributes) {
    for (const [name, value] of Object.entries(options.attributes)) {
      node.setAttribute(name, String(value));
    }
  }
  for (const child of children) {
    node.append(child);
  }
  return node;
}

export function textPair(label, value, className = "") {
  const wrapper = element("div", { className });
  wrapper.append(element("span", { text: label }), element("strong", { text: value }));
  return wrapper;
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return "—";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 10 || unit === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "—";
  }
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remaining = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`;
  }
  return `${minutes}:${String(remaining).padStart(2, "0")}`;
}

export function formatDate(value) {
  if (!value) {
    return "—";
  }
  const normalized = value.length === 10 ? `${value}T12:00:00` : value;
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" }).format(parsed);
}

export function formatDateTime(value) {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(parsed);
}

export function formatPercent(value, digits = 0) {
  if (!Number.isFinite(value)) {
    return "—";
  }
  return `${value.toFixed(digits)}%`;
}

export const statusLabels = Object.freeze({
  pending: "Enfileirado",
  running: "Em andamento",
  succeeded: "Concluído",
  failed: "Falhou",
  cancelled: "Cancelado",
});

export const phaseLabels = Object.freeze({
  queued: "Na fila",
  claiming: "Preparando",
  loading_model: "Carregando modelo",
  transcribing: "Transcrevendo",
  finalizing: "Finalizando",
  cancelling: "Cancelamento solicitado",
  completed: "Finalizado",
});

export function statusLabel(status) {
  return statusLabels[status] || "Estado desconhecido";
}

export function phaseLabel(phase) {
  return phaseLabels[phase] || "Fase desconhecida";
}

export function plainExcerpt(value) {
  return String(value || "").replace(/<\/?mark>/gi, "");
}
