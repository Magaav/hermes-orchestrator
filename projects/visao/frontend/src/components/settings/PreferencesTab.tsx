import { useEffect, useState } from "react";
import { Bell, Hand, LoaderCircle, Moon, Sun } from "lucide-react";
import { applyPreferences, settingsAPI, type Preferences } from "../../settings/api";

const fallback: Preferences = { theme: "day", touchEnabled: true, notifications: false };

export function PreferencesTab() {
  const [value, setValue] = useState<Preferences>(fallback);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    void settingsAPI.preferences()
      .then((current) => {
        setValue(current);
        applyPreferences(current);
      })
      .catch((reason) => setMessage(reason instanceof Error ? reason.message : "Não foi possível carregar as preferências."))
      .finally(() => setLoading(false));
  }, []);

  async function update(next: Preferences) {
    setSaving(true);
    setMessage("");
    try {
      if (next.notifications && "Notification" in window && Notification.permission === "default") {
        const permission = await Notification.requestPermission();
        next = { ...next, notifications: permission === "granted" };
      }
      const saved = await settingsAPI.savePreferences(next);
      setValue(saved);
      applyPreferences(saved);
      setMessage("Preferências atualizadas.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Não foi possível salvar.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="settings-loading"><LoaderCircle className="studio-spinner" size={22} /> Carregando preferências…</div>;

  return (
    <section className="settings-preferences" aria-label="Preferências">
      <button className="settings-toggle-card" type="button" disabled={saving} onClick={() => void update({ ...value, theme: value.theme === "day" ? "night" : "day" })}>
        <span>{value.theme === "day" ? <Sun size={22} /> : <Moon size={22} />}</span>
        <div><strong>Visão dia / noite</strong><small>{value.theme === "day" ? "Tema claro ativo" : "Tema noturno ativo"}</small></div>
        <b>{value.theme === "day" ? "Dia" : "Noite"}</b>
      </button>
      <button className="settings-toggle-card" type="button" disabled={saving} onClick={() => void update({ ...value, touchEnabled: !value.touchEnabled })}>
        <span><Hand size={22} /></span>
        <div><strong>Eventos de toque</strong><small>Otimizações de interação para telas sensíveis</small></div>
        <b>{value.touchEnabled ? "Ativos" : "Inativos"}</b>
      </button>
      <button className="settings-toggle-card" type="button" disabled={saving} onClick={() => void update({ ...value, notifications: !value.notifications })}>
        <span><Bell size={22} /></span>
        <div><strong>Notificações</strong><small>Avisos permitidos neste navegador</small></div>
        <b>{value.notifications ? "Ativas" : "Inativas"}</b>
      </button>
      {message && <p className="settings-feedback" role="status">{message}</p>}
    </section>
  );
}
