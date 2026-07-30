import { useEffect, useMemo, useState } from "react";
import { KeyRound, Save, ShieldCheck } from "lucide-react";
import type { AdminData } from "../../settings/api";
import { ManagedSelect } from "./ManagedSelect";

type Props = {
  data: AdminData;
  busy: boolean;
  canManage: boolean;
  onSave: (roleID: string, permissions: string[]) => Promise<void>;
};

export function ActionsTab({ data, busy, canManage, onSave }: Props) {
  const initialRole = data.roles.find((role) => role.id !== "owner")?.id || data.roles[0]?.id || "";
  const [roleID, setRoleID] = useState(initialRole);
  const role = data.roles.find((current) => current.id === roleID) || data.roles[0];
  const [permissions, setPermissions] = useState<string[]>(role?.permissions || []);
  const editable = Boolean(role && role.id !== "owner" && canManage);
  const grouped = useMemo(() => {
    const groups = new Map<string, AdminData["capabilities"]>();
    for (const capability of data.capabilities) {
      groups.set(capability.group, [...(groups.get(capability.group) || []), capability]);
    }
    return [...groups.entries()];
  }, [data.capabilities]);

  useEffect(() => {
    setPermissions(role?.permissions || []);
  }, [role]);

  function toggle(capability: string) {
    if (!editable) return;
    setPermissions((current) => current.includes(capability)
      ? current.filter((item) => item !== capability)
      : [...current, capability]);
  }

  return (
    <>
      <div className="settings-section-heading">
        <div><p className="eyebrow">PERMISSÕES</p><h2>Ações por cargo</h2><p>Defina exatamente o que cada cargo pode executar.</p></div>
        <span className="settings-admin__count"><KeyRound size={16} /> {data.capabilities.length} ações</span>
      </div>
      <section className="settings-actions">
        <header>
          <div>
            <label htmlFor="settings-action-role">Cargo</label>
            <ManagedSelect
              ariaLabel="Cargo para configurar ações"
              value={role?.id || ""}
              options={data.roles.map((item) => ({
                value: item.id,
                label: item.name,
                detail: `Nível ${item.priority}`,
                color: item.color
              }))}
              onChange={setRoleID}
            />
          </div>
          <div className="settings-actions__role">
            <span style={{ background: role?.color }}><ShieldCheck size={18} /></span>
            <div><strong>{role?.name}</strong><small>{permissions.length} ações atribuídas</small></div>
          </div>
          <button className="button button--primary" type="button" disabled={busy || !editable} onClick={() => void onSave(role.id, permissions)}>
            <Save size={17} /> Salvar ações
          </button>
        </header>
        {!editable && <p className="settings-actions__locked">{role?.id === "owner" ? "As ações do Owner são protegidas e não podem ser reduzidas." : "Seu cargo não permite atribuir ações."}</p>}
        <div className="settings-actions__groups">
          {grouped.map(([group, capabilities]) => (
            <fieldset key={group}>
              <legend>{group}</legend>
              {capabilities.map((capability) => (
                <label key={capability.id} className={permissions.includes(capability.id) ? "is-active" : ""}>
                  <input type="checkbox" checked={permissions.includes(capability.id)} disabled={!editable || busy} onChange={() => toggle(capability.id)} />
                  <span><strong>{capability.label}</strong><small>{capability.id}</small></span>
                </label>
              ))}
            </fieldset>
          ))}
        </div>
      </section>
    </>
  );
}
