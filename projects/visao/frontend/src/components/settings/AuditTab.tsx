import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { settingsAPI, type AuditEntry } from "../../settings/api";

export function AuditTab() {
  const [items, setItems] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void settingsAPI.audit().then((result) => setItems(result.items)).catch((reason) => setError(reason instanceof Error ? reason.message : "Não foi possível carregar os registros."));
  }, []);

  if (error) return <p className="settings-feedback is-error" role="alert">{error}</p>;
  if (!items) return <div className="settings-loading"><LoaderCircle className="studio-spinner" size={22} /> Carregando registros…</div>;

  return (
    <section className="settings-audit">
      <div className="settings-section-heading">
        <div><p className="eyebrow">AUDITORIA CUD</p><h2>Registros de alteração</h2></div>
        <small>{items.length} eventos mais recentes</small>
      </div>
      <div className="settings-table-wrap">
        <table>
          <thead><tr><th>Data</th><th>Usuário</th><th>Tipo</th><th>Tabela</th><th>ID</th><th>Motivo</th><th>JSON</th></tr></thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>{new Date(item.date).toLocaleString("pt-BR")}</td>
                <td>{item.user}</td>
                <td><span className={`settings-action settings-action--${item.type}`}>{item.type}</span></td>
                <td><code>{item.table}</code></td>
                <td><code>{item.recordId}</code></td>
                <td>{item.reason}</td>
                <td><details><summary>Ver</summary><pre>{JSON.stringify(item.json, null, 2)}</pre></details></td>
              </tr>
            ))}
            {!items.length && <tr><td colSpan={7} className="settings-empty">Nenhuma alteração registrada.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
