import { ArrowLeft, FileCheck2, FileClock, Plus, Search } from "lucide-react";
import type { SubmissionSummary } from "../form/types";
import type { SessionUser } from "../form/api";
import { AppHeader } from "./AppHeader";

type Props = {
  items: SubmissionSummary[];
  loading: boolean;
  user: SessionUser | null;
  onCreate: () => void;
  onOpen: (id: string) => void;
  onBack: () => void;
  onLogout: () => void;
};

function displayDate(value: string) {
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

export function Dashboard({ items, loading, user, onCreate, onOpen, onBack, onLogout }: Props) {
  const submitted = items.filter((item) => item.status === "submitted").length;
  const drafts = items.length - submitted;
  return (
    <div className="dashboard-shell">
      <AppHeader user={user} onLogout={onLogout} />
      <main className="dashboard">
        <button className="module-back" onClick={onBack}><ArrowLeft size={16} /> Início</button>
        <div className="dashboard__heading">
          <div>
            <p className="eyebrow">GESTÃO DE PROCESSOS</p>
            <h1>Atendimentos</h1>
            <p className="muted">Acompanhe rascunhos e fichas encaminhadas ao jurídico.</p>
          </div>
          <button className="button button--primary" onClick={onCreate}><Plus size={18} /> Novo atendimento</button>
        </div>
        <div className="metrics">
          <article><span><FileClock size={20} /></span><div><strong>{drafts}</strong><small>Rascunhos</small></div></article>
          <article><span><FileCheck2 size={20} /></span><div><strong>{submitted}</strong><small>Finalizados</small></div></article>
        </div>
        <section className="records-card">
          <div className="records-card__header">
            <div><h2>Fichas recentes</h2><p className="muted">Até 200 processos, ordenados pela última atualização.</p></div>
            <span className="search-hint"><Search size={16} /> {items.length} registro{items.length === 1 ? "" : "s"}</span>
          </div>
          {loading ? <div className="empty-state">Carregando atendimentos…</div> : items.length === 0 ? (
            <div className="empty-state">
              <span><FileClock size={28} /></span>
              <h3>Nenhum atendimento ainda</h3>
              <p>Crie a primeira ficha para começar a organizar o processo.</p>
              <button className="button button--secondary" onClick={onCreate}><Plus size={17} /> Criar atendimento</button>
            </div>
          ) : (
            <div className="record-list">
              {items.map((item) => (
                <button className="record-row" key={item.id} onClick={() => onOpen(item.id)}>
                  <span className={`status-dot status-dot--${item.status}`} />
                  <span className="record-row__main">
                    <strong>{item.atendimento || "Atendimento sem número"}</strong>
                    <small>{item.corretor || "Corretor não informado"}</small>
                  </span>
                  <span className={`status-pill status-pill--${item.status}`}>{item.status === "submitted" ? "Finalizado" : "Rascunho"}</span>
                  <span className="record-row__date">{displayDate(item.updatedAt)}</span>
                  <span className="record-row__arrow">→</span>
                </button>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
