import { ArrowLeft, Check, CheckCircle2, ChevronLeft, ChevronRight, Cloud, CloudOff, Download, Info, LoaderCircle, LogOut, Printer, Send, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { APIError, api } from "../form/api";
import { checklistGroups, dealGroups, legalRecipients, peopleGroups, propertyGroups, requiredFieldKeys, startGroups, steps, type FormGroup } from "../form/schema";
import type { ChecklistEntry, FormPayload, Submission } from "../form/types";
import { Brand } from "./Brand";
import { Checklist } from "./Checklist";
import { FieldGrid } from "./FieldGrid";

type Props = {
  initial: Submission | null;
  initialPayload: FormPayload;
  onBack: () => void;
  onLogout: () => void;
};

type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";

function FormGroups({ groups, payload, invalid, onValue }: { groups: FormGroup[]; payload: FormPayload; invalid: Set<string>; onValue: (key: string, value: string) => void }) {
  return <div className="form-groups">
    {groups.map((group) => {
      const enabled = !group.enabledBy || payload.values[group.enabledBy] === "yes";
      return <section className={`form-card ${group.enabledBy && !enabled ? "form-card--disabled" : ""}`} key={group.id}>
        <div className="form-card__heading">
          <div><h3>{group.title}</h3>{group.description && <p>{group.description}</p>}</div>
          {group.enabledBy && (
            <label className="switch-row">
              <input type="checkbox" checked={enabled} onChange={(event) => onValue(group.enabledBy!, event.target.checked ? "yes" : "no")} />
              <span aria-hidden="true" />
              {enabled ? "Incluído" : "Não incluído"}
            </label>
          )}
        </div>
        {enabled && <FieldGrid fields={group.fields} values={payload.values} invalid={invalid} onChange={onValue} />}
      </section>;
    })}
  </div>;
}

function Review({ payload, missing, checklistDone }: { payload: FormPayload; missing: string[]; checklistDone: number }) {
  const totalDocs = checklistGroups.reduce((sum, group) => sum + group.documents.length, 0);
  const labelByKey = new Map([...startGroups, ...propertyGroups, ...peopleGroups, ...dealGroups].flatMap((group) => group.fields.map((field) => [field.key, field.label])));
  return <div className="review-layout">
    <section className="review-hero">
      <span className={missing.length ? "review-hero__icon review-hero__icon--warning" : "review-hero__icon"}>{missing.length ? <ShieldAlert size={28} /> : <CheckCircle2 size={28} />}</span>
      <div>
        <p className="eyebrow">PRONTO PARA O JURÍDICO?</p>
        <h3>{missing.length ? `${missing.length} campo${missing.length === 1 ? "" : "s"} obrigatório${missing.length === 1 ? "" : "s"} pendente${missing.length === 1 ? "" : "s"}` : "Informações essenciais preenchidas"}</h3>
        <p>{missing.length ? "Volte às etapas indicadas para concluir a ficha antes do envio." : "Revise os documentos e as condições do negócio antes de finalizar."}</p>
      </div>
    </section>
    <div className="review-grid">
      <section className="form-card">
        <div className="form-card__heading"><div><p className="eyebrow">CAMPOS ESSENCIAIS</p><h3>{requiredFieldKeys.length - missing.length} de {requiredFieldKeys.length} preenchidos</h3></div></div>
        <div className="review-checks">
          {requiredFieldKeys.map((key) => <div className={missing.includes(key) ? "is-pending" : "is-done"} key={key}><span>{missing.includes(key) ? "!" : <Check size={13} />}</span>{labelByKey.get(key) || key}</div>)}
        </div>
      </section>
      <section className="form-card">
        <div className="form-card__heading"><div><p className="eyebrow">CHECKLIST</p><h3>{checklistDone} de {totalDocs} tratados</h3></div></div>
        <div className="progress-bar progress-bar--large"><span style={{ width: `${Math.round((checklistDone / totalDocs) * 100)}%` }} /></div>
        <p className="muted review-copy">Itens marcados como Recebido, Validado ou Não se aplica entram no progresso. Anotações e PDFs continuam disponíveis no processo.</p>
      </section>
    </div>
    <section className="form-card legal-recipients">
      <div className="form-card__heading"><div><p className="eyebrow">DESTINATÁRIOS</p><h3>Envio obrigatório ao jurídico</h3><p>Anexe a ficha à proposta assinada e encaminhe toda a documentação em PDF.</p></div></div>
      <div>{legalRecipients.map((email) => <a href={`mailto:${email}`} key={email}>{email}</a>)}</div>
    </section>
    <aside className="finance-warning"><Info size={20} /><p><strong>Regra de financiamento:</strong> o comprador deve apresentar o comprovante definitivo de liberação do saldo a pagar pelo banco antes do envio do processo.</p></aside>
  </div>;
}

function PrintableRecord({ payload }: { payload: FormPayload }) {
  const groups = [...startGroups, ...propertyGroups, ...peopleGroups, ...dealGroups];
  return <article className="print-sheet">
    <header><Brand /><div><strong>Checklist e Tratativas</strong><small>Gestão de processos integrada</small></div></header>
    {groups.map((group) => {
      if (group.enabledBy && payload.values[group.enabledBy] !== "yes") return null;
      return <section key={group.id}><h2>{group.title}</h2><div>{group.fields.map((field) => <p key={field.key}><span>{field.label}</span><strong>{payload.values[field.key] || "—"}</strong></p>)}</div></section>;
    })}
    <section><h2>Checklist documental</h2><div>{checklistGroups.flatMap((group) => group.documents.map((document) => {
      const entry = payload.checklist[document.id];
      return <p key={document.id}><span>{document.title}</span><strong>{entry?.status === "validated" ? "Validado" : entry?.status === "received" ? "Recebido" : entry?.status === "not_applicable" ? "Não se aplica" : "Pendente"}{entry?.notes ? ` — ${entry.notes}` : ""}</strong></p>;
    }))}</div></section>
  </article>;
}

export function FormWorkspace({ initial, initialPayload, onBack, onLogout }: Props) {
  const [payload, setPayload] = useState<FormPayload>(initialPayload);
  const [submission, setSubmission] = useState<Submission | null>(initial);
  const [stepIndex, setStepIndex] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>(initial ? "saved" : "idle");
  const [saveError, setSaveError] = useState("");
  const [downloadingDocuments, setDownloadingDocuments] = useState(false);
  const [invalid, setInvalid] = useState<Set<string>>(new Set());
  const revision = useRef(0);

  const markChanged = useCallback((next: FormPayload) => {
    revision.current += 1;
    setPayload(next);
    setDirty(true);
    setSaveState("dirty");
    if (submission?.status === "submitted") setSubmission({ ...submission, status: "draft" });
  }, [submission]);

  const setValue = useCallback((key: string, value: string) => {
    markChanged({ ...payload, values: { ...payload.values, [key]: value } });
    if (invalid.has(key) && value.trim()) {
      const next = new Set(invalid); next.delete(key); setInvalid(next);
    }
  }, [invalid, markChanged, payload]);

  const setChecklist = useCallback((id: string, entry: ChecklistEntry) => {
    markChanged({ ...payload, checklist: { ...payload.checklist, [id]: entry } });
  }, [markChanged, payload]);

  const persist = useCallback(async (status: "draft" | "submitted" = "draft") => {
    const activeRevision = revision.current;
    setSaveState("saving");
    setSaveError("");
    try {
      const saved = await api.save(submission?.id, status, payload);
      setSubmission(saved);
      if (revision.current === activeRevision) {
        setDirty(false);
        setSaveState("saved");
      } else {
        setSaveState("dirty");
      }
      return saved;
    } catch (reason) {
      setSaveState("error");
      setSaveError(reason instanceof Error ? reason.message : "Falha ao salvar.");
      throw reason;
    }
  }, [payload, submission?.id]);

  useEffect(() => {
    if (!dirty || submission?.status === "submitted") return;
    const timer = window.setTimeout(() => { void persist("draft").catch(() => undefined); }, 900);
    return () => window.clearTimeout(timer);
  }, [dirty, payload, persist, submission?.status]);

  const missing = useMemo(() => requiredFieldKeys.filter((key) => !payload.values[key]?.trim()), [payload.values]);
  const checklistDone = useMemo(() => Object.values(payload.checklist).filter((entry) => entry.status !== "pending").length, [payload.checklist]);
  const totalDocs = Object.keys(payload.checklist).length;
  const attachedDocumentCount = useMemo(() => Object.values(payload.checklist).reduce((sum, entry) => sum + entry.files.length, 0), [payload.checklist]);
  const overallProgress = Math.round((((requiredFieldKeys.length - missing.length) + checklistDone) / (requiredFieldKeys.length + totalDocs)) * 100);

  async function goBack() {
    if (dirty) {
      try { await persist("draft"); } catch { return; }
    }
    onBack();
  }

  async function submit() {
    if (missing.length) {
      setInvalid(new Set(missing));
      const firstMissing = missing[0];
      if (firstMissing.startsWith("meta.")) setStepIndex(0);
      else if (firstMissing.startsWith("property.")) setStepIndex(2);
      else if (firstMissing.startsWith("buyer.") || firstMissing.startsWith("seller.")) setStepIndex(3);
      else setStepIndex(4);
      return;
    }
    try {
      await persist("submitted");
      setStepIndex(5);
    } catch (reason) {
      if (reason instanceof APIError && reason.fields.length) setInvalid(new Set(reason.fields));
    }
  }

  async function downloadDocuments() {
    if (!attachedDocumentCount) return;
    setDownloadingDocuments(true);
    setSaveError("");
    try {
      const saved = dirty || !submission ? await persist("draft") : submission;
      const anchor = document.createElement("a");
      anchor.href = `/api/submissions/${saved.id}/documents`;
      anchor.download = `atendimento-${saved.id}-documentos.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : "Não foi possível preparar os documentos.");
    } finally {
      setDownloadingDocuments(false);
    }
  }

  const current = steps[stepIndex];
  return (
    <div className="workspace">
      <aside className="workspace-nav">
        <Brand compact />
        <button className="workspace-nav__back" onClick={() => void goBack()}><ArrowLeft size={17} /> Atendimentos</button>
        <nav aria-label="Etapas do formulário">
          {steps.map((step, index) => (
            <button key={step.id} className={index === stepIndex ? "is-active" : index < stepIndex ? "is-complete" : ""} onClick={() => setStepIndex(index)}>
              <span>{index < stepIndex ? <Check size={14} /> : step.index}</span>
              <div><small>ETAPA {step.index}</small><strong>{step.shortTitle}</strong></div>
            </button>
          ))}
        </nav>
        <div className="workspace-nav__progress">
          <div><span>Progresso geral</span><strong>{overallProgress}%</strong></div>
          <div className="progress-bar"><span style={{ width: `${overallProgress}%` }} /></div>
        </div>
        <button className="workspace-nav__logout" onClick={onLogout}><LogOut size={16} /> Sair</button>
      </aside>
      <main className="workspace-main">
        <header className="workspace-header">
          <button className="mobile-back" onClick={() => void goBack()}><ArrowLeft size={19} /></button>
          <div className="workspace-header__identity">
            <small>ATENDIMENTO</small>
            <strong>{payload.values["meta.atendimento"] || "Novo processo"}</strong>
          </div>
          <div className={`save-state save-state--${saveState}`} title={saveError}>
            {saveState === "error" ? <CloudOff size={16} /> : <Cloud size={16} />}
            {saveState === "saving" ? "Salvando…" : saveState === "dirty" ? "Alterações pendentes" : saveState === "error" ? "Falha ao salvar" : saveState === "saved" ? "Salvo" : "Novo rascunho"}
          </div>
          <button className="button button--secondary workspace-header__documents" type="button" disabled={!attachedDocumentCount || downloadingDocuments || saveState === "saving"} onClick={() => void downloadDocuments()}>
            {downloadingDocuments ? <LoaderCircle className="studio-spinner" size={17} /> : <Download size={17} />} Baixar documentos
          </button>
          <button className="button button--quiet print-action" onClick={() => window.print()}><Printer size={17} /> Imprimir</button>
        </header>
        <div className="workspace-content">
          <div className="step-heading">
            <p className="eyebrow">ETAPA {current.index} DE {String(steps.length).padStart(2, "0")}</p>
            <h1>{current.title}</h1>
            <p>{current.description}</p>
          </div>
          {stepIndex === 0 && <FormGroups groups={startGroups} payload={payload} invalid={invalid} onValue={setValue} />}
          {stepIndex === 1 && <>
            <aside className="finance-warning"><ShieldAlert size={20} /><p><strong>De extrema importância:</strong> antes do envio, o comprador deve apresentar o comprovante definitivo de liberação do saldo pelo banco.</p></aside>
            <Checklist groups={checklistGroups} entries={payload.checklist} onChange={setChecklist} />
          </>}
          {stepIndex === 2 && <FormGroups groups={propertyGroups} payload={payload} invalid={invalid} onValue={setValue} />}
          {stepIndex === 3 && <>
            <aside className="helper-note"><Info size={18} /><p>Se houver mais partes envolvidas, crie uma ficha adicional para preservar a identificação individual de cada participante.</p></aside>
            <FormGroups groups={peopleGroups} payload={payload} invalid={invalid} onValue={setValue} />
          </>}
          {stepIndex === 4 && <FormGroups groups={dealGroups} payload={payload} invalid={invalid} onValue={setValue} />}
          {stepIndex === 5 && <Review payload={payload} missing={missing} checklistDone={checklistDone} />}
          {saveError && <p className="save-error" role="alert"><CloudOff size={16} /> {saveError}</p>}
          <footer className="step-footer">
            <button className="button button--secondary" onClick={() => setStepIndex((value) => Math.max(0, value - 1))} disabled={stepIndex === 0}><ChevronLeft size={18} /> Anterior</button>
            <span>Etapa {stepIndex + 1} de {steps.length}</span>
            {stepIndex < steps.length - 1 ? (
              <button className="button button--primary" onClick={() => setStepIndex((value) => Math.min(steps.length - 1, value + 1))}>Continuar <ChevronRight size={18} /></button>
            ) : (
              <button className="button button--primary" onClick={() => void submit()} disabled={saveState === "saving" || submission?.status === "submitted"}>
                {submission?.status === "submitted" ? <><CheckCircle2 size={18} /> Processo finalizado</> : <><Send size={17} /> Finalizar processo</>}
              </button>
            )}
          </footer>
        </div>
      </main>
      <PrintableRecord payload={payload} />
    </div>
  );
}
