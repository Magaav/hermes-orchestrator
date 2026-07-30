import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight, Clock3, Download, History, Images, LoaderCircle, Trash2 } from "lucide-react";
import {
  deleteStudioSession,
  getStudioSession,
  listStudioSessions,
  type StudioSession,
  type StudioSessionSummary
} from "../studio/api";
import { formatStudioElapsed } from "../studio/time";
import { cleanedFilename, createZip, downloadZip } from "../studio/zip";
import { StudioCompareModal } from "./StudioCompareModal";

type Props = {
  onBack: () => void;
};

const dateFormat = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "medium",
  timeStyle: "short"
});
const byteFormat = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${byteFormat.format(value / 1024)} KB`;
  return `${byteFormat.format(value / (1024 * 1024))} MB`;
}

export function StudioSessions({ onBack }: Props) {
  const [items, setItems] = useState<StudioSessionSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [session, setSession] = useState<StudioSession | null>(null);
  const [selectedPhotoId, setSelectedPhotoId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");

  const loadList = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      const result = await listStudioSessions(signal);
      setItems(result.items);
    } catch (reason) {
      if (!signal?.aborted) setError(reason instanceof Error ? reason.message : "Não foi possível carregar as sessões.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadList(controller.signal);
    return () => controller.abort();
  }, [loadList]);

  useEffect(() => {
    if (!selectedId) {
      setSession(null);
      setSelectedPhotoId(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void getStudioSession(selectedId, controller.signal)
      .then(setSession)
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Não foi possível abrir a sessão.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selectedId]);

  async function removeSession() {
    if (!session || deleting) return;
    const confirmed = window.confirm("Excluir esta sessão e remover definitivamente todas as imagens e registros de uso?");
    if (!confirmed) return;
    setDeleting(true);
    setError("");
    try {
      await deleteStudioSession(session.id);
      setItems((current) => current.filter((item) => item.id !== session.id));
      setSelectedId(null);
      setSession(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível excluir a sessão.");
    } finally {
      setDeleting(false);
    }
  }

  async function exportSession() {
    if (!session?.photos.length || exporting) return;
    setExporting(true);
    setError("");
    try {
      const entries: Array<{ name: string; blob: Blob }> = [];
      for (const [index, photo] of session.photos.entries()) {
        const response = await fetch(photo.outputUrl, { credentials: "same-origin" });
        if (!response.ok) throw new Error("Não foi possível recuperar uma imagem da sessão.");
        entries.push({ name: cleanedFilename(photo.sourceName, index), blob: await response.blob() });
      }
      downloadZip(await createZip(entries));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível baixar esta sessão.");
    } finally {
      setExporting(false);
    }
  }

  const selectedIndex = selectedId ? items.findIndex((item) => item.id === selectedId) : -1;
  const selectedPhoto = session?.photos.find((photo) => photo.id === selectedPhotoId);

  if (selectedId) {
    return (
      <main className="studio studio-sessions" data-session-id={selectedId}>
        <div className="studio-session__topbar">
          <button className="module-back" type="button" onClick={() => setSelectedId(null)}><ArrowLeft size={16} /> Sessões</button>
          <div className="studio-session__navigation" aria-label="Navegar entre sessões">
            <button type="button" aria-label="Sessão mais recente" disabled={selectedIndex <= 0} onClick={() => setSelectedId(items[selectedIndex - 1]?.id || null)}><ChevronLeft size={18} /></button>
            <span>{selectedIndex + 1} / {items.length}</span>
            <button type="button" aria-label="Sessão mais antiga" disabled={selectedIndex < 0 || selectedIndex >= items.length - 1} onClick={() => setSelectedId(items[selectedIndex + 1]?.id || null)}><ChevronRight size={18} /></button>
          </div>
        </div>

        <div className="studio-sessions__heading">
          <div>
            <p className="eyebrow">SESSÃO ARQUIVADA</p>
            <h1>{session ? dateFormat.format(new Date(session.createdAt)) : "Carregando…"}</h1>
            <p>{session?.photoCount || 0} foto{session?.photoCount === 1 ? "" : "s"} · {formatStudioElapsed(session?.totalElapsedMs || 0)} de tratamento</p>
          </div>
          <div className="studio-session__actions">
            <button className="button button--secondary" type="button" disabled={!session?.photos.length || exporting} onClick={() => void exportSession()}>
              {exporting ? <LoaderCircle size={17} className="studio-spinner" /> : <Download size={17} />} Baixar AVIF
            </button>
            <button className="button button--quiet studio-session__delete" type="button" disabled={!session || deleting} onClick={() => void removeSession()}>
              {deleting ? <LoaderCircle size={17} className="studio-spinner" /> : <Trash2 size={17} />} Excluir
            </button>
          </div>
        </div>

        {error && <p className="studio-message" role="alert">{error}</p>}
        {loading ? (
          <div className="studio-sessions__loading"><LoaderCircle size={22} className="studio-spinner" /> Abrindo sessão…</div>
        ) : session?.photos.length ? (
          <section className="studio-grid" aria-label="Fotos da sessão">
            {session.photos.map((photo) => (
              <button className="studio-photo studio-session-photo" type="button" key={photo.id} onClick={() => setSelectedPhotoId(photo.id)}>
                <img src={photo.outputUrl} alt={photo.sourceName} />
                <span className="studio-photo__timer">
                  <Clock3 aria-hidden="true" size={13} />
                  <span className="studio-photo__timer-value">{formatStudioElapsed(photo.elapsedMs)}</span>
                </span>
                <span className="studio-photo__state">{photo.sourceName}</span>
              </button>
            ))}
          </section>
        ) : (
          <div className="studio-sessions__empty"><Images size={28} /><h2>Sessão vazia</h2><p>Nenhuma foto foi arquivada nesta sessão.</p></div>
        )}

        {selectedPhoto && (
          <StudioCompareModal
            name={selectedPhoto.sourceName}
            sourceUrl={selectedPhoto.sourceUrl}
            outputUrl={selectedPhoto.outputUrl}
            usage={selectedPhoto.proof.usage}
            sourceBytes={selectedPhoto.sourceBytes}
            outputBytes={selectedPhoto.outputBytes}
            elapsedMs={selectedPhoto.elapsedMs}
            onClose={() => setSelectedPhotoId(null)}
          />
        )}
      </main>
    );
  }

  return (
    <main className="studio studio-sessions">
      <button className="module-back" type="button" onClick={onBack}><ArrowLeft size={16} /> Studio</button>
      <div className="studio-sessions__heading">
        <div>
          <p className="eyebrow">MEMÓRIA DO STUDIO</p>
          <h1>Sessões</h1>
          <p>Navegue pelos tratamentos anteriores e recupere suas imagens.</p>
        </div>
        <span className="studio-sessions__count"><History size={17} /> {items.length}</span>
      </div>

      {error && <p className="studio-message" role="alert">{error}</p>}
      {loading ? (
        <div className="studio-sessions__loading"><LoaderCircle size={22} className="studio-spinner" /> Carregando sessões…</div>
      ) : items.length ? (
        <section className="studio-session-list" aria-label="Histórico de sessões">
          {items.map((item) => (
            <button className="studio-session-row" type="button" key={item.id} data-session-id={item.id} onClick={() => setSelectedId(item.id)}>
              <span className="studio-session-row__icon"><Images size={20} /></span>
              <span className="studio-session-row__main">
                <strong>{dateFormat.format(new Date(item.createdAt))}</strong>
                <small>{item.photoCount} foto{item.photoCount === 1 ? "" : "s"} · {formatBytes(item.totalBytes)}</small>
              </span>
              <span className="studio-session-row__time"><Clock3 size={14} /> {formatStudioElapsed(item.totalElapsedMs)}</span>
              <ChevronRight size={18} />
            </button>
          ))}
        </section>
      ) : (
        <div className="studio-sessions__empty"><History size={28} /><h2>Nenhuma sessão arquivada</h2><p>Seu próximo lote tratado aparecerá aqui automaticamente.</p></div>
      )}
    </main>
  );
}
