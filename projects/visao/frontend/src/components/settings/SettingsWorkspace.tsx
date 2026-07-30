import { useMemo, useState } from "react";
import { ArrowLeft, Database, ListTree, Settings, ShieldCheck } from "lucide-react";
import type { SessionUser } from "../../form/api";
import { AppHeader } from "../AppHeader";
import { AdminTab } from "./AdminTab";
import { AuditTab } from "./AuditTab";
import { InventoryTab } from "./InventoryTab";
import { PreferencesTab } from "./PreferencesTab";
import "../../settings.css";

type Tab = "preferences" | "database" | "audit" | "admin";
type Props = { user: SessionUser | null; onBack: () => void; onLogout: () => void };

const tabs = [
  { id: "preferences", label: "Configurações", capability: "settings.preferences", icon: Settings },
  { id: "database", label: "Banco de Dados", capability: "settings.inventory", icon: Database },
  { id: "audit", label: "Registros", capability: "settings.audit", icon: ListTree },
  { id: "admin", label: "Admin", capability: "settings.admin", icon: ShieldCheck }
] as const;

export function SettingsWorkspace({ user, onBack, onLogout }: Props) {
  const visibleTabs = useMemo(() => tabs.filter((tab) => user?.capabilities?.includes(tab.capability)), [user]);
  const [active, setActive] = useState<Tab>(visibleTabs[0]?.id || "preferences");

  return (
    <div className="dashboard-shell settings-shell">
      <AppHeader user={user} onLogout={onLogout} />
      <main className="settings-workspace">
        <button className="module-back" type="button" onClick={onBack}><ArrowLeft size={16} /> Espaço de trabalho</button>
        <div className="settings-heading">
          <div><p className="eyebrow">GESTÃO DO WORKSPACE</p><h1>Configurações</h1><p>Preferências, dados, auditoria e acesso em um único lugar.</p></div>
        </div>
        <nav className="settings-tabs" aria-label="Configurações">
          {visibleTabs.map((tab) => {
            const Icon = tab.icon;
            return <button type="button" key={tab.id} className={active === tab.id ? "is-active" : ""} onClick={() => setActive(tab.id)}>
              <Icon size={17} /> {tab.label}
            </button>;
          })}
        </nav>
        <div className="settings-content">
          {active === "preferences" && <PreferencesTab />}
          {active === "database" && <InventoryTab />}
          {active === "audit" && <AuditTab />}
          {active === "admin" && user && <AdminTab currentEmail={user.email} currentCapabilities={user.capabilities || []} />}
        </div>
      </main>
    </div>
  );
}
