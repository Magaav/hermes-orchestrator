import { ArrowUpRight, ClipboardList, Images, Settings as SettingsIcon } from "lucide-react";
import type { SessionUser } from "../form/api";
import { AppHeader } from "./AppHeader";

const modules = [
  {
    id: "atendimentos",
    name: "Atendimento",
    description: "Cadastros, documentos e tratativas de venda.",
    capability: "atendimento.view",
    icon: ClipboardList
  },
  {
    id: "studio",
    name: "Studio",
    description: "Tratamento de fotos em lote, com até 50 imagens.",
    capability: "studio.view",
    icon: Images
  },
  {
    id: "settings",
    name: "Configurações",
    description: "Preferências, dados, auditoria e controle de acesso.",
    capability: "settings.view",
    icon: SettingsIcon
  }
] as const;

export type ModuleId = typeof modules[number]["id"];

type Props = {
  user: SessionUser | null;
  onOpenModule: (id: ModuleId) => void;
  onLogout: () => void;
};

export function Home({ user, onOpenModule, onLogout }: Props) {
  const firstName = user?.name?.trim().split(/\s+/)[0];
  const visibleModules = modules.filter((module) => user?.capabilities?.includes(module.capability));

  return (
    <div className="dashboard-shell">
      <AppHeader user={user} onLogout={onLogout} />
      <main className="home">
        <section className="home__intro">
          <p className="eyebrow">ESPAÇO DE TRABALHO</p>
          <h1>{firstName ? `Olá, ${firstName}.` : "Olá."}</h1>
          <p>Escolha um módulo para começar.</p>
        </section>

        <section className="module-section" aria-labelledby="module-section-title">
          <div className="module-section__heading">
            <h2 id="module-section-title">Módulos</h2>
            <span>{visibleModules.length} disponíveis</span>
          </div>
          <div className="module-grid">
            {visibleModules.map((module) => {
              const Icon = module.icon;
              return (
                <button className="module-card" key={module.id} onClick={() => onOpenModule(module.id)}>
                  <span className="module-card__icon"><Icon size={30} strokeWidth={1.8} /></span>
                  <span className="module-card__content">
                    <strong>{module.name}</strong>
                    <small>{module.description}</small>
                  </span>
                  <span className="module-card__action">Abrir módulo <ArrowUpRight size={17} /></span>
                </button>
              );
            })}
          </div>
        </section>
      </main>
    </div>
  );
}
