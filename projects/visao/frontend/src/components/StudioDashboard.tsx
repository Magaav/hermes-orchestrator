import { useEffect, useState } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight, CircleGauge, Images, Sigma, Users } from "lucide-react";
import {
  getStudioUsage,
  type StudioUsageDashboard as DashboardData,
  type StudioUsagePeriod,
  type StudioUsageScope
} from "../studio/api";
import { StudioUsageChart } from "./StudioUsageChart";

type Props = { onBack: () => void };
const numberFormat = new Intl.NumberFormat("pt-BR");

function today() {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

export function StudioDashboard({ onBack }: Props) {
  const [period, setPeriod] = useState<StudioUsagePeriod>("month");
  const [scope, setScope] = useState<StudioUsageScope>("me");
  const [anchor, setAnchor] = useState(today);
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void getStudioUsage(period, scope, anchor, controller.signal)
      .then(setData)
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Não foi possível carregar o painel.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [anchor, period, scope]);

  return (
    <main className="studio studio-dashboard">
      <button className="module-back" type="button" onClick={onBack}><ArrowLeft size={16} /> Studio</button>
      <div className="studio-dashboard__heading">
        <div>
          <p className="eyebrow">USO DO STUDIO</p>
          <h1>Dashboard</h1>
          <p>Tokens confirmados pelo Codex por foto, pessoa e período.</p>
        </div>
        <div className="studio-segmented" aria-label="Escopo do painel">
          <button type="button" className={scope === "me" ? "is-active" : ""} onClick={() => setScope("me")}>Meu uso</button>
          <button type="button" className={scope === "all" ? "is-active" : ""} onClick={() => setScope("all")}><Users size={15} /> Todos</button>
        </div>
      </div>

      <section className="studio-dashboard__toolbar" aria-label="Período">
        <div className="studio-segmented">
          {([
            ["day", "Dia"],
            ["month", "Mês"],
            ["year", "Ano"]
          ] as Array<[StudioUsagePeriod, string]>).map(([value, label]) => (
            <button
              type="button"
              key={value}
              className={period === value ? "is-active" : ""}
              onClick={() => setPeriod(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="studio-period-nav">
          <button type="button" onClick={() => data && setAnchor(data.range.previous)} disabled={!data} aria-label="Período anterior"><ChevronLeft size={18} /></button>
          <strong>{data?.range.label || "Carregando…"}</strong>
          <button type="button" onClick={() => data && setAnchor(data.range.next)} disabled={!data} aria-label="Próximo período"><ChevronRight size={18} /></button>
        </div>
      </section>

      {error && <p className="studio-message" role="alert">{error}</p>}

      <section className={`studio-dashboard__content ${loading ? "is-loading" : ""}`} aria-busy={loading}>
        <div className="studio-kpis">
          <article>
            <span><CircleGauge size={20} /></span>
            <div><small>Média confirmada por foto</small><strong>{numberFormat.format(data?.summary.averageTokens || 0)}</strong><em>tokens reportados</em></div>
          </article>
          <article>
            <span><Sigma size={20} /></span>
            <div><small>Tokens confirmados</small><strong>{numberFormat.format(data?.summary.totalTokens || 0)}</strong><em>sem estimativas</em></div>
          </article>
          <article>
            <span><Images size={20} /></span>
            <div><small>Fotos com tokens reportados</small><strong>{numberFormat.format(data?.summary.meteredPictures || 0)}</strong><em>{data?.summary.pictures || 0} processadas no período</em></div>
          </article>
        </div>

        <article className="studio-dashboard__chart-card">
          <header>
            <div>
              <h2>Consumo no período</h2>
              <p>{scope === "me" ? "Seus tokens confirmados pelo Codex" : "Tokens confirmados de todos os usuários"}</p>
            </div>
            <span>tokens</span>
          </header>
          <StudioUsageChart points={data?.series || []} />
        </article>

        {!!data?.summary.partialPictures && (
          <p className="studio-dashboard__partial">
            {data.summary.partialPictures} execução{data.summary.partialPictures === 1 ? "" : "ões"} com medição parcial. Totais, médias e gráfico incluem somente os componentes reportados pelo Codex; nenhum componente ausente foi estimado.
          </p>
        )}
        {!!data?.summary.unreportedPictures && (
          <p className="studio-dashboard__partial">
            {data.summary.unreportedPictures} execução{data.summary.unreportedPictures === 1 ? "" : "ões"} sem contagem reportada, fora dos totais, médias e gráfico.
          </p>
        )}

        {scope === "all" && (
          <article className="studio-users-card">
            <header><h2>Uso por pessoa</h2><span>{data?.users.length || 0} usuário{data?.users.length === 1 ? "" : "s"}</span></header>
            <div>
              {data?.users.map((item) => (
                <div className="studio-user-row" key={item.id}>
                  <span className="studio-user-row__avatar">{item.name.trim().charAt(0).toUpperCase() || "U"}</span>
                  <strong>{item.name || "Usuário"}</strong>
                  <small>{item.pictures} foto{item.pictures === 1 ? "" : "s"}</small>
                  <div><b>{numberFormat.format(item.totalTokens)}</b><span>tokens totais</span></div>
                  <div><b>{numberFormat.format(item.averageTokens)}</b><span>média / foto</span></div>
                </div>
              ))}
              {!data?.users.length && !loading && <p className="studio-users-card__empty">Nenhum uso registrado neste período.</p>}
            </div>
          </article>
        )}
      </section>
    </main>
  );
}
