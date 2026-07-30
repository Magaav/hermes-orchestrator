import { useEffect, useState } from "react";
import { Database, FileArchive, FolderOpen, LoaderCircle } from "lucide-react";
import { settingsAPI, type Inventory } from "../../settings/api";

const byteFormat = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const numberFormat = new Intl.NumberFormat("pt-BR");

function bytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${byteFormat.format(value / 1024)} KB`;
  if (value < 1024 ** 3) return `${byteFormat.format(value / 1024 ** 2)} MB`;
  return `${byteFormat.format(value / 1024 ** 3)} GB`;
}

export function InventoryTab() {
  const [data, setData] = useState<Inventory | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void settingsAPI.inventory().then(setData).catch((reason) => setError(reason instanceof Error ? reason.message : "Não foi possível carregar o inventário."));
  }, []);

  if (error) return <p className="settings-feedback is-error" role="alert">{error}</p>;
  if (!data) return <div className="settings-loading"><LoaderCircle className="studio-spinner" size={22} /> Inspecionando o projeto…</div>;

  return (
    <section className="settings-inventory">
      <div className="settings-section-heading">
        <div><p className="eyebrow">ARMAZENAMENTO</p><h2>Arquivos e mídia</h2></div>
        <small>Atualizado em {new Date(data.generatedAt).toLocaleString("pt-BR")}</small>
      </div>
      <div className="settings-storage-grid">
        {data.storage.map((area) => (
          <article key={area.id}>
            <span>{area.id === "media" ? <FileArchive size={20} /> : <FolderOpen size={20} />}</span>
            <div><strong>{area.label}</strong><small>{area.path}</small></div>
            <b>{bytes(area.bytes)}</b>
            <em>{numberFormat.format(area.files)} arquivos</em>
          </article>
        ))}
      </div>

      <article className="settings-database-card">
        <header><span><Database size={21} /></span><div><h2>SQLite</h2><p>{data.database.path} · {bytes(data.database.bytes)}</p></div></header>
        <div className="settings-table-wrap">
          <table>
            <thead><tr><th>Tabela</th><th>Colunas</th><th>Registros</th></tr></thead>
            <tbody>
              {data.database.tables.map((table) => (
                <tr key={table.name}><td><code>{table.name}</code></td><td>{table.columns}</td><td>{numberFormat.format(table.rows)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
}
