import { useEffect, useState } from "react";
import { KeyRound, LoaderCircle, Pencil, Plus, ShieldCheck, Trash2, UserPlus, Users } from "lucide-react";
import { settingsAPI, type AdminData, type Role } from "../../settings/api";
import { ActionsTab } from "./ActionsTab";
import { ManagedSelect } from "./ManagedSelect";

type RoleDraft = Omit<Role, "id" | "system">;
const emptyRole: RoleDraft = { name: "", color: "#005596", priority: 100, permissions: [] };

export function AdminTab({ currentEmail, currentCapabilities }: { currentEmail: string; currentCapabilities: string[] }) {
  const [data, setData] = useState<AdminData | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [adminSection, setAdminSection] = useState<"roles" | "actions" | "users">("roles");
  const [editingRole, setEditingRole] = useState("");
  const [roleDraft, setRoleDraft] = useState<RoleDraft>(emptyRole);
  const [email, setEmail] = useState("");
  const [newUserRole, setNewUserRole] = useState("member");

  const canManageRoles = currentCapabilities.includes("admin.roles.manage");
  const canManageActions = currentCapabilities.includes("admin.actions.manage");
  const canInviteUsers = currentCapabilities.includes("admin.users.invite");
  const canAssignRoles = currentCapabilities.includes("admin.roles.assign_lower");
  const canRevokeUsers = currentCapabilities.includes("admin.users.revoke_lower");

  async function refresh() {
    setError("");
    try {
      setData(await settingsAPI.admin());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível carregar a administração.");
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      setMessage(success);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível concluir a ação.");
    } finally {
      setBusy(false);
    }
  }

  function editRole(role: Role) {
    setEditingRole(role.id);
    setRoleDraft({ name: role.name, color: role.color, priority: role.priority, permissions: [...role.permissions] });
  }

  async function saveRole() {
    await run(
      () => editingRole ? settingsAPI.updateRole(editingRole, roleDraft) : settingsAPI.createRole(roleDraft),
      editingRole ? "Cargo atualizado." : "Cargo criado."
    );
    setEditingRole("");
    setRoleDraft(emptyRole);
  }

  async function addUser() {
    const target = email.trim().toLowerCase();
    if (!target) return;
    await run(() => settingsAPI.saveUser(target, [newUserRole]), "Usuário autorizado.");
    setEmail("");
  }

  async function toggleUserRole(targetEmail: string, currentRoles: string[], roleID: string) {
    const next = currentRoles.includes(roleID)
      ? currentRoles.filter((current) => current !== roleID)
      : [...currentRoles, roleID];
    if (!next.length) return;
    await run(() => settingsAPI.updateUser(targetEmail, next), "Cargos atualizados.");
  }

  async function saveActions(roleID: string, permissions: string[]) {
    await run(() => settingsAPI.updateRoleActions(roleID, permissions), "Ações do cargo atualizadas.");
  }

  if (!data && !error) return <div className="settings-loading"><LoaderCircle className="studio-spinner" size={22} /> Carregando administração…</div>;
  if (!data) return <p className="settings-feedback is-error" role="alert">{error}</p>;

  return (
    <section className="settings-admin">
      <nav className="settings-subtabs" aria-label="Administração">
        <button type="button" className={adminSection === "roles" ? "is-active" : ""} onClick={() => setAdminSection("roles")}><ShieldCheck size={16} /> Cargos</button>
        <button type="button" className={adminSection === "actions" ? "is-active" : ""} onClick={() => setAdminSection("actions")}><KeyRound size={16} /> Ações</button>
        <button type="button" className={adminSection === "users" ? "is-active" : ""} onClick={() => setAdminSection("users")}><Users size={16} /> Usuários</button>
      </nav>

      {adminSection === "roles" ? <>
        <div className="settings-section-heading">
          <div><p className="eyebrow">CONTROLE DE ACESSO</p><h2>Cargos</h2><p>Hierarquia central de telas, recursos e funcionalidades.</p></div>
          <span className="settings-admin__count"><ShieldCheck size={16} /> {data.roles.length} cargos</span>
        </div>

        <div className="settings-admin__layout">
          <div className="settings-role-list">
            {data.roles.map((role) => (
              <article key={role.id}>
                <i style={{ background: role.color }} />
                <div><strong>{role.name}</strong><small>Nível {role.priority} · {role.permissions.length} permissões</small></div>
                {role.system ? <span>Sistema</span> : (
                  <div className="settings-row-actions">
                    <button type="button" disabled={!canManageRoles} onClick={() => editRole(role)} aria-label={`Editar ${role.name}`}><Pencil size={15} /></button>
                    <button type="button" disabled={busy || !canManageRoles} onClick={() => void run(() => settingsAPI.deleteRole(role.id), "Cargo removido.")} aria-label={`Excluir ${role.name}`}><Trash2 size={15} /></button>
                  </div>
                )}
              </article>
            ))}
          </div>

          <form className="settings-role-editor" onSubmit={(event) => { event.preventDefault(); void saveRole(); }}>
            <header><Plus size={18} /><strong>{editingRole ? "Editar cargo" : "Novo cargo"}</strong></header>
            <div className="settings-role-editor__fields">
              <label>Nome<input value={roleDraft.name} maxLength={80} required onChange={(event) => setRoleDraft({ ...roleDraft, name: event.target.value })} /></label>
              <label>Nível<input type="number" min={0} max={999} value={roleDraft.priority} onChange={(event) => setRoleDraft({ ...roleDraft, priority: Number(event.target.value) })} /></label>
              <label>Cor<input type="color" value={roleDraft.color} onChange={(event) => setRoleDraft({ ...roleDraft, color: event.target.value })} /></label>
            </div>
            <div className="settings-role-editor__actions">
              {editingRole && <button className="button button--quiet" type="button" onClick={() => { setEditingRole(""); setRoleDraft(emptyRole); }}>Cancelar</button>}
              <button className="button button--primary" type="submit" disabled={busy || !canManageRoles}>{editingRole ? "Salvar cargo" : "Criar cargo"}</button>
            </div>
          </form>
        </div>
      </> : adminSection === "actions" ? (
        <ActionsTab data={data} busy={busy} canManage={canManageActions} onSave={saveActions} />
      ) : <>
        <div className="settings-section-heading">
          <div><p className="eyebrow">LOGIN</p><h2>Usuários autorizados</h2></div>
          <span className="settings-admin__count"><Users size={16} /> {data.users.length} ativos</span>
        </div>

        <form className="settings-add-user" onSubmit={(event) => { event.preventDefault(); void addUser(); }}>
          <UserPlus size={18} />
          <input type="email" required disabled={!canInviteUsers} placeholder="email@empresa.com" value={email} onChange={(event) => setEmail(event.target.value)} />
          <ManagedSelect
            ariaLabel="Cargo inicial"
            value={newUserRole}
            disabled={!canInviteUsers}
            options={data.roles.filter((role) => role.id !== "owner").map((role) => ({
              value: role.id,
              label: role.name,
              detail: `Nível ${role.priority}`,
              color: role.color
            }))}
            onChange={setNewUserRole}
          />
          <button className="button button--primary" type="submit" disabled={busy || !canInviteUsers}>Adicionar</button>
        </form>

        <div className="settings-user-list">
          {data.users.map((user) => (
            <article key={user.email}>
              <span className="settings-user-avatar">
                {(user.name || user.email).slice(0, 1).toUpperCase()}
                {user.picture && <img src={user.picture} alt="" referrerPolicy="no-referrer" onError={(event) => { event.currentTarget.style.display = "none"; }} />}
              </span>
              <div className="settings-user-identity"><strong>{user.name || "Aguardando primeiro login"}</strong><small>{user.email}</small></div>
              <div className="settings-user-roles">
                {data.roles.map((role) => {
                  const checked = user.roles.includes(role.id);
                  const ownerLocked = role.id === "owner";
                  return (
                    <label key={role.id} className={checked ? "is-active" : ""}>
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={busy || ownerLocked || !canAssignRoles}
                        onChange={() => void toggleUserRole(user.email, user.roles, role.id)}
                      />
                      <i style={{ background: role.color }} /> {role.name}
                    </label>
                  );
                })}
              </div>
              <button
                className="button button--quiet settings-user-delete"
                type="button"
                disabled={busy || user.email === currentEmail || !canRevokeUsers}
                onClick={() => void run(() => settingsAPI.deleteUser(user.email), "Acesso revogado.")}
              >
                <Trash2 size={16} /> Remover
              </button>
            </article>
          ))}
        </div>
      </>}
      {(message || error) && <p className={`settings-feedback ${error ? "is-error" : ""}`} role={error ? "alert" : "status"}>{error || message}</p>}
    </section>
  );
}
