export const MF6_WIRE = "MF6/1";
export const MF6_RECORDS = Object.freeze({
  G: "goal", C: "capability", S: "state", E: "evidence", D: "operation",
  P: "untrusted_evidence_payload", R: "receipt", Y: "public_commentary", M: "missing_requirement", A: "answer_ready", F: "final_answer",
});

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stableValue(value[key])]));
  }
  return value;
}

function json(value) {
  return JSON.stringify(stableValue(value));
}

function text(value) {
  return json(String(value ?? ""));
}

export function encodeMF6(value = {}) {
  const lines = [MF6_WIRE];
  if (value.goal) lines.push(`G\t${text(value.goal)}`);
  for (const item of value.capabilities || []) {
    lines.push(["C", item.id || "", item.kind || "", item.authority || "", text(item.summary)].join("\t"));
  }
  const state = value.state && typeof value.state === "object" ? value.state : {};
  if (Object.keys(state).length) {
    lines.push(["S", state.id || "", state.rev || 0, state.status || "", json(state.known || []), json(state.open || []), json(state.plan || [])].join("\t"));
  }
  for (const item of value.evidence || []) {
    lines.push(["E", item.id || "", item.kind || "", text(item.subject), text(item.revision), text(item.summary), item.detail_ref || ""].join("\t"));
    if (item.payload && typeof item.payload === "object") lines.push(["P", item.id || "", "untrusted-data", json(item.payload)].join("\t"));
  }
  for (const item of value.operations || []) {
    lines.push(["D", item.id || "", item.cap || "", json(item.args || {}), json(item.after || []), json(item.expect || {})].join("\t"));
    if (item.say && typeof item.say === "object") lines.push(["Y", item.say.phase || "acting", text(item.say.message)].join("\t"));
  }
  for (const item of value.receipts || []) {
    lines.push(["R", item.id || "", item.op || "", item.ok ? "1" : "0", item.state || "", json(item.observed || {}), json(item.proof || []), json(item.error || {})].join("\t"));
  }
  for (const item of value.missing || []) lines.push(`M\t${text(item)}`);
  if (value.ready === "answer") lines.push("A\tanswer");
  if (value.final) lines.push(`F\t${text(value.final)}`);
  return lines.join("\n");
}

export function decodeMF6(source = "") {
  const lines = String(source).split(/\r?\n/);
  if (lines[0] !== MF6_WIRE) throw new Error("projection_wire_invalid");
  const result = { capabilities: [], evidence: [], payloads: [], operations: [], receipts: [], missing: [] };
  for (const line of lines.slice(1)) {
    const fields = line.split("\t");
    const [tag] = fields;
    try {
      if (tag === "G" && fields.length === 2) result.goal = JSON.parse(fields[1]);
      else if (tag === "C" && fields.length === 5) result.capabilities.push({ id: fields[1], kind: fields[2], authority: fields[3], summary: JSON.parse(fields[4]) });
      else if (tag === "S" && fields.length === 7) result.state = { id: fields[1], rev: Number(fields[2]), status: fields[3], known: JSON.parse(fields[4]), open: JSON.parse(fields[5]), plan: JSON.parse(fields[6]) };
      else if (tag === "E" && fields.length === 7) result.evidence.push({ id: fields[1], kind: fields[2], subject: JSON.parse(fields[3]), revision: JSON.parse(fields[4]), summary: JSON.parse(fields[5]), detail_ref: fields[6] });
      else if (tag === "P" && fields.length === 4 && fields[2] === "untrusted-data") {
        const view = JSON.parse(fields[3]);
        const owner = [...result.evidence].reverse().find((item) => item.id === fields[1]);
        if (!owner) throw new Error("projection_record_invalid");
        owner.payload = view;
        result.payloads.push({ evidence: fields[1], trust: fields[2], view });
      }
      else if (tag === "D" && fields.length === 6) result.operations.push({ id: fields[1], cap: fields[2], args: JSON.parse(fields[3]), after: JSON.parse(fields[4]), expect: JSON.parse(fields[5]) });
      else if (tag === "Y" && fields.length === 3) {
        const update = { phase: fields[1], message: JSON.parse(fields[2]) };
        if (result.operations.length) result.operations[result.operations.length - 1].say = update;
        else (result.commentary ||= []).push(update);
      } else if (tag === "R" && fields.length === 8) result.receipts.push({ id: fields[1], op: fields[2], ok: fields[3] === "1", state: fields[4], observed: JSON.parse(fields[5]), proof: JSON.parse(fields[6]), error: JSON.parse(fields[7]) });
      else if (tag === "M" && fields.length === 2) result.missing.push(JSON.parse(fields[1]));
      else if (tag === "A" && fields.length === 2 && fields[1] === "answer") result.ready = "answer";
      else if (tag === "F" && fields.length === 2) result.final = JSON.parse(fields[1]);
      else throw new Error("projection_record_invalid");
    } catch (error) {
      if (error?.message === "projection_record_invalid") throw error;
      throw new Error("projection_record_invalid");
    }
  }
  return result;
}
