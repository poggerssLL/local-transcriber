export const byId = (id) => document.getElementById(id);
export function message(value) { byId("status").textContent = String(value); }
export function activity(value) { byId("activity").hidden = false; byId("activity-text").textContent = String(value); }
export function bytes(value) { return new Intl.NumberFormat("pt-BR").format(value) + " bytes"; }
export function renderSubjects(subjects) {
  const select = byId("subject");
  select.replaceChildren();
  const empty = document.createElement("option"); empty.value = ""; empty.textContent = "Selecione uma matéria"; select.append(empty);
  for (const subject of subjects) { const option = document.createElement("option"); option.value = subject.id; option.textContent = subject.name; select.append(option); }
  select.value = subjects.length === 1 ? subjects[0].id : "";
}
export function renderTranscript(data) {
  byId("result").hidden = false;
  byId("transcript").value = data.text;
  const segments = byId("segments"); segments.replaceChildren();
  for (const part of data.segments || []) {
    const row = document.createElement("p");
    const stamp = document.createElement("strong");
    stamp.textContent = `${Math.floor(part.start_seconds / 60)}:${String(Math.floor(part.start_seconds % 60)).padStart(2, "0")}–${Math.floor(part.end_seconds / 60)}:${String(Math.floor(part.end_seconds % 60)).padStart(2, "0")} `;
    row.append(stamp, document.createTextNode(part.text)); segments.append(row);
  }
}
