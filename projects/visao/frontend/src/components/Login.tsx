import { ArrowRight, LockKeyhole, ShieldCheck } from "lucide-react";
import { Brand } from "./Brand";

const errorMessages: Record<string, string> = {
  google_cancelled: "O acesso com Google foi cancelado.",
  missing_code: "O Google não devolveu uma autorização válida.",
  invalid_state: "A autorização expirou. Tente entrar novamente.",
  exchange_failed: "O Google não conseguiu concluir a autorização.",
  profile_failed: "Não foi possível carregar seu perfil Google.",
  email_not_allowed: "Este e-mail Google ainda não está autorizado para a Visão.",
  user_failed: "Não foi possível registrar seu acesso.",
  session_failed: "Não foi possível iniciar sua sessão."
};

function GoogleIcon() {
  return <svg className="google-icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M21.6 12.23c0-.71-.06-1.4-.18-2.06H12v3.9h5.38a4.6 4.6 0 0 1-2 3.02v2.53h3.24c1.9-1.75 2.98-4.33 2.98-7.39Z"/><path fill="#34A853" d="M12 22c2.7 0 4.97-.9 6.62-2.38l-3.24-2.53c-.9.6-2.05.96-3.38.96-2.6 0-4.81-1.76-5.6-4.13H3.06v2.61A10 10 0 0 0 12 22Z"/><path fill="#FBBC05" d="M6.4 13.92a6 6 0 0 1 0-3.84V7.47H3.06a10 10 0 0 0 0 9.06l3.34-2.61Z"/><path fill="#EA4335" d="M12 5.95c1.47 0 2.79.5 3.82 1.5l2.87-2.87A9.62 9.62 0 0 0 12 2a10 10 0 0 0-8.94 5.47l3.34 2.61c.79-2.37 3-4.13 5.6-4.13Z"/></svg>;
}

export function Login() {
  const errorCode = new URLSearchParams(window.location.search).get("auth_error") || "";
  const error = errorMessages[errorCode];

  return (
    <main className="login-shell">
      <section className="login-story">
        <Brand />
        <div className="login-story__content">
          <p className="eyebrow">GESTÃO DE PROCESSOS INTEGRADA</p>
          <h1>Do checklist ao contrato, sem perder nenhum detalhe.</h1>
          <p>Uma ficha única para reunir documentos, partes e condições da venda com clareza e rastreabilidade.</p>
        </div>
        <p className="login-story__footer">Visão Vendas · Indaiatuba</p>
      </section>
      <section className="login-panel">
        <section className="login-card">
          <span className="login-card__icon"><LockKeyhole size={22} /></span>
          <p className="eyebrow">ÁREA RESTRITA</p>
          <h2>Entre com sua conta Google</h2>
          <p className="muted">Use o e-mail autorizado da equipe. Nenhuma senha é armazenada pela Visão.</p>
          {error && <p className="form-error" role="alert">{error}</p>}
          <a className="button button--google button--large" href="/auth/google/start">
            <GoogleIcon /> Continuar com Google <ArrowRight size={18} />
          </a>
          <p className="privacy-note"><ShieldCheck size={15} /> Acesso protegido pelo Google e restrito aos e-mails autorizados.</p>
        </section>
      </section>
    </main>
  );
}
