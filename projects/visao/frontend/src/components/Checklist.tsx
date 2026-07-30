import { ExternalLink, FileText, Paperclip, Upload, X } from "lucide-react";
import { ChangeEvent, useRef, useState } from "react";
import { api } from "../form/api";
import type { ChecklistGroup } from "../form/schema";
import type { ChecklistEntry, UploadRef } from "../form/types";
import { DocumentModal } from "./DocumentModal";

type Props = {
  groups: ChecklistGroup[];
  entries: Record<string, ChecklistEntry>;
  onChange: (id: string, entry: ChecklistEntry) => void;
};

function fileSize(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function DocumentRow({ id, title, detail, entry, onChange, onOpen }: { id: string; title: string; detail?: string; entry: ChecklistEntry; onChange: (entry: ChecklistEntry) => void; onOpen: (file: UploadRef) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  async function addFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const uploaded = await api.upload(file);
      onChange({ ...entry, status: entry.status === "pending" ? "received" : entry.status, files: [...entry.files, uploaded] });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha no envio.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <article className="document-row">
      <div className="document-row__status"><FileText size={19} /></div>
      <div className="document-row__body">
        <h4>{title}</h4>
        {detail && <p>{detail}</p>}
        {entry.files.length > 0 && <div className="attached-files">
          {entry.files.map((file, index) => (
            <span key={`${file.id}-${index}`}>
              <Paperclip size={13} /><button className="attached-files__open" type="button" onClick={() => onOpen(file)}>{file.name}</button><small>{fileSize(file.size)}</small>
              <button type="button" onClick={() => onChange({ ...entry, files: entry.files.filter((_, fileIndex) => fileIndex !== index) })} aria-label={`Remover ${file.name}`}><X size={13} /></button>
            </span>
          ))}
        </div>}
        {error && <small className="form-error">{error}</small>}
      </div>
      <div className="document-row__actions">
        <select value={entry.status} onChange={(event) => onChange({ ...entry, status: event.target.value as ChecklistEntry["status"] })} aria-label={`Status de ${title}`}>
          <option value="pending">Pendente</option>
          <option value="received">Recebido</option>
          <option value="validated">Validado</option>
          <option value="not_applicable">Não se aplica</option>
        </select>
        <button className="button button--upload" type="button" onClick={() => input.current?.click()} disabled={uploading}>
          <Upload size={15} /> {uploading ? "Enviando…" : "Anexar PDF"}
        </button>
        <input ref={input} type="file" accept="application/pdf,.pdf" onChange={addFile} hidden />
      </div>
      <label className="document-row__notes">
        <span>Anotações / status da validação</span>
        <input value={entry.notes} onChange={(event) => onChange({ ...entry, notes: event.target.value })} placeholder="Observações sobre este documento" />
      </label>
    </article>
  );
}

export function Checklist({ groups, entries, onChange }: Props) {
  const [selectedFile, setSelectedFile] = useState<UploadRef | null>(null);
  return <div className="checklist-groups">
    {groups.map((group) => (
      <section className="form-card checklist-card" key={group.id}>
        <div className="form-card__heading">
          <div><p className="eyebrow">{group.optional ? "SE HOUVER PARTICIPANTE" : "DOCUMENTAÇÃO"}</p><h3>{group.title}</h3><p>{group.description}</p></div>
          {group.optional && <span className="optional-pill">Opcional</span>}
        </div>
        <div className="document-list">
          {group.documents.map((document) => (
            <DocumentRow key={document.id} {...document} entry={entries[document.id]} onChange={(entry) => onChange(document.id, entry)} onOpen={setSelectedFile} />
          ))}
        </div>
      </section>
    ))}
    <aside className="legal-instruction">
      <ExternalLink size={21} />
      <div><strong>Instrução de envio ao jurídico</strong><p>Reúna toda a documentação em PDF, anexe esta ficha junto à proposta assinada e encaminhe aos destinatários indicados na etapa de revisão.</p></div>
    </aside>
    {selectedFile && <DocumentModal file={selectedFile} onClose={() => setSelectedFile(null)} />}
  </div>;
}
