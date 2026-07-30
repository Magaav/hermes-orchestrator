import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Check, CircleAlert, ExternalLink, LoaderCircle, Server, UserRound } from "lucide-react";
import {
  getStudioAccessStatus,
  startStudioCodexLogin,
  type StudioAccessStatus
} from "../studio/api";

type Props = {
  onBack: () => void;
};

export function StudioSettings({ onBack }: Props) {
  const [status, setStatus] = useState<StudioAccessStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [startingLogin, setStartingLogin] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const next = await getStudioAccessStatus();
      setStatus(next);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível verificar o Studio.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh(true);
  }, [refresh]);

  useEffect(() => {
    if (status?.login.state !== "pending") return;
    const timer = window.setTimeout(() => void refresh(), 2000);
    return () => window.clearTimeout(timer);
  }, [refresh, status?.checkedAt, status?.login.state]);

  async function login() {
    setStartingLogin(true);
    setError("");
    try {
      const result = await startStudioCodexLogin();
      setStatus((current) => current ? {
        ...current,
        account: { state: "checking" },
        datacenter: { state: "unavailable" },
        login: result.login,
        checkedAt: new Date().toISOString()
      } : null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível iniciar o acesso ao Codex.");
    } finally {
      setStartingLogin(false);
    }
  }

  const ready = status?.account.state === "connected"
    && status.runtime.state === "ready"
    && status.datacenter.state === "ready";
  const loginPending = status?.login.state === "pending";

  return (
    <main className="studio studio-settings">
      <button className="module-back" onClick={onBack}><ArrowLeft size={16} /> Studio</button>
      <div className="studio-settings__heading">
        <p className="eyebrow">ACESSO AO DATACENTER</p>
        <h1>Configurações do Studio</h1>
        <p>Conecte sua conta Codex para tratar fotos com o Master:frontier.</p>
      </div>

      <section className="studio-access-card" aria-label="Acesso do Studio">
        {loading ? (
          <div className="studio-access-loading" role="status">
            <LoaderCircle size={22} className="studio-spinner" />
            Verificando o acesso…
          </div>
        ) : (
          <>
            <div className="studio-access-row">
              <span className="studio-access-row__icon"><UserRound size={21} /></span>
              <div>
                <strong>Conta Codex</strong>
                <small>{status?.account.state === "connected" ? "Conta ChatGPT autenticada" : loginPending ? "Aguardando confirmação" : "Login necessário"}</small>
              </div>
              <span className={`studio-status studio-status--${status?.account.state === "connected" ? "ready" : "off"}`}>
                {status?.account.state === "connected" ? "Conectada" : loginPending ? "Pendente" : "Desconectada"}
              </span>
            </div>

            <div className="studio-access-row">
              <span className="studio-access-row__icon"><Server size={21} /></span>
              <div>
                <strong>Datacenter</strong>
                <small>Codex · Master:frontier</small>
              </div>
              <span className={`studio-status studio-status--${ready ? "ready" : "off"}`}>
                {ready ? "Operacional" : "Indisponível"}
              </span>
            </div>

            {ready ? (
              <div className="studio-access-message studio-access-message--ready" role="status">
                <Check size={20} />
                <div>
                  <strong>Studio conectado</strong>
                  <span>O Codex está pronto. Tokens serão exibidos somente quando reportados pelo serviço.</span>
                </div>
              </div>
            ) : (
              <div className="studio-access-message">
                <CircleAlert size={20} />
                <div>
                  <strong>Acesso necessário</strong>
                  <span>Entre com o Codex para liberar o tratamento no datacenter.</span>
                </div>
              </div>
            )}

            {loginPending && status?.login.verificationUrl && status.login.userCode ? (
              <div className="studio-device-login">
                <span>Seu código</span>
                <strong>{status.login.userCode}</strong>
                <a className="button button--primary" href={status.login.verificationUrl} target="_blank" rel="noreferrer">
                  Abrir login Codex <ExternalLink size={16} />
                </a>
                <small>Digite o código na página do Codex. Esta tela confirmará o acesso automaticamente.</small>
              </div>
            ) : !ready && (
              <button className="button button--primary studio-login-button" onClick={() => void login()} disabled={startingLogin}>
                {startingLogin ? <LoaderCircle size={17} className="studio-spinner" /> : <UserRound size={17} />}
                {startingLogin ? "Iniciando…" : "Entrar com Codex"}
              </button>
            )}
          </>
        )}
        {error && <p className="studio-settings__error" role="alert">{error}</p>}
      </section>
    </main>
  );
}
