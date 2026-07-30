import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, Clock3, Download, History, LayoutDashboard, LoaderCircle, Settings, Sparkles, Trash2, UploadCloud, X } from "lucide-react";
import type { SessionUser } from "../form/api";
import {
  cleanStudioPhoto,
  createStudioSession,
  getStudioAccessStatus,
  saveStudioSessionPhoto,
  type StudioProof
} from "../studio/api";
import { formatStudioElapsed } from "../studio/time";
import { cleanedFilename, createZip, downloadZip } from "../studio/zip";
import { AppHeader } from "./AppHeader";
import { StudioCompareModal } from "./StudioCompareModal";
import { StudioDashboard } from "./StudioDashboard";
import { StudioSessions } from "./StudioSessions";
import { StudioSettings } from "./StudioSettings";

const MAX_PHOTOS = 50;
const MAX_BYTES = 20 * 1024 * 1024;
const WORKER_LANES = 10;
const ACCEPTED_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "image/avif"]);

type PhotoState = "ready" | "queued" | "cleaning" | "cleaned" | "failed";
type StudioView = "photos" | "sessions" | "dashboard" | "settings";

type StudioPhoto = {
  id: string;
  file: File;
  sourceUrl: string;
  output?: Blob;
  outputUrl?: string;
  state: PhotoState;
  progress: string;
  error: string;
  proof?: StudioProof;
  startedAt?: number;
  elapsedMs: number;
  archived?: boolean;
};

type Props = {
  user: SessionUser | null;
  onBack: () => void;
  onLogout: () => void;
};

const progressLabels: Record<string, string> = {
  preparing: "Preparando",
  accepted: "Foto recebida",
  "envelope-starting": "Iniciando Master:frontier",
  "session-starting": "Iniciando",
  "session-started": "Sessão pronta",
  reconstructing: "Tratando foto",
  "artifact-generated": "Conferindo resultado",
  finalizing: "Finalizando",
  "encoding-avif": "Convertendo para AVIF"
};

export function Studio({ user, onBack, onLogout }: Props) {
  const [photos, setPhotos] = useState<StudioPhoto[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [watermarkAuthorized, setWatermarkAuthorized] = useState(false);
  const [message, setMessage] = useState("");
  const [view, setView] = useState<StudioView>("photos");
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [selectedPhotoId, setSelectedPhotoId] = useState<string | null>(null);
  const [clock, setClock] = useState(Date.now);
  const inputRef = useRef<HTMLInputElement>(null);
  const photosRef = useRef<StudioPhoto[]>([]);
  const urlsRef = useRef(new Set<string>());
  const batchRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => () => {
    mountedRef.current = false;
    batchRef.current?.abort();
    for (const url of urlsRef.current) URL.revokeObjectURL(url);
  }, []);

  useEffect(() => {
    if (!photos.some((photo) => photo.state === "cleaning" && photo.startedAt)) return;
    const timer = window.setInterval(() => setClock(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [photos]);

  function commit(update: (current: StudioPhoto[]) => StudioPhoto[]) {
    setPhotos((current) => {
      const next = update(current);
      photosRef.current = next;
      return next;
    });
  }

  function patchPhoto(id: string, patch: Partial<StudioPhoto>) {
    commit((current) => current.map((photo) => photo.id === id ? { ...photo, ...patch } : photo));
  }

  function addFiles(files: FileList | File[]) {
    if (busy) return;
    const candidates = Array.from(files);
    const valid = candidates.filter((file) => ACCEPTED_TYPES.has(file.type) && file.size <= MAX_BYTES);
    const capacity = Math.max(0, MAX_PHOTOS - photosRef.current.length);
    const accepted = valid.slice(0, capacity);
    const additions = accepted.map((file) => {
      const sourceUrl = URL.createObjectURL(file);
      urlsRef.current.add(sourceUrl);
      return {
        id: crypto.randomUUID(),
        file,
        sourceUrl,
        state: "ready" as const,
        progress: "Pronta",
        error: "",
        elapsedMs: 0
      };
    });
    if (additions.length) commit((current) => [...current, ...additions]);

    const rejected = candidates.length - valid.length;
    const overflow = valid.length - accepted.length;
    if (overflow > 0) setMessage(`Limite de ${MAX_PHOTOS} fotos atingido.`);
    else if (rejected > 0) setMessage(`${rejected} arquivo${rejected === 1 ? "" : "s"} ignorado${rejected === 1 ? "" : "s"}. Use JPEG, PNG, WebP ou AVIF de até 20 MB.`);
    else setMessage("");
  }

  function removePhoto(id: string) {
    if (busy) return;
    const photo = photosRef.current.find((item) => item.id === id);
    if (!photo) return;
    for (const url of [photo.sourceUrl, photo.outputUrl]) {
      if (!url) continue;
      URL.revokeObjectURL(url);
      urlsRef.current.delete(url);
    }
    if (selectedPhotoId === id) setSelectedPhotoId(null);
    commit((current) => current.filter((item) => item.id !== id));
  }

  function removeAll() {
    if (busy) return;
    for (const photo of photosRef.current) {
      URL.revokeObjectURL(photo.sourceUrl);
      if (photo.outputUrl) URL.revokeObjectURL(photo.outputUrl);
    }
    urlsRef.current.clear();
    commit(() => []);
    setCurrentSessionId(null);
    setSelectedPhotoId(null);
    setMessage("");
  }

  async function cleanAll() {
    const queue = photosRef.current.filter((photo) => photo.state === "ready" || photo.state === "failed");
    if (!queue.length || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const access = await getStudioAccessStatus();
      if (access.datacenter.state !== "ready") {
        setMessage("Configure o acesso ao datacenter na engrenagem antes de tratar as fotos.");
        setBusy(false);
        return;
      }
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Não foi possível verificar o acesso ao datacenter.");
      setBusy(false);
      return;
    }
    let activeSessionId = currentSessionId;
    if (!activeSessionId) {
      try {
        const session = await createStudioSession();
        activeSessionId = session.id;
        setCurrentSessionId(session.id);
      } catch (reason) {
        setMessage(reason instanceof Error ? reason.message : "Não foi possível criar a sessão do Studio.");
        setBusy(false);
        return;
      }
    }
    const controller = new AbortController();
    batchRef.current = controller;
    const queuedIds = new Set(queue.map((photo) => photo.id));
    commit((current) => current.map((photo) => queuedIds.has(photo.id) ? {
      ...photo,
      state: "queued",
      progress: "Na fila",
      error: "",
      elapsedMs: 0,
      startedAt: undefined
    } : photo));

    const laneCount = Math.min(WORKER_LANES, queue.length);
    await Promise.all(Array.from({ length: laneCount }, async (_, laneIndex) => {
      for (let index = laneIndex; index < queue.length; index += laneCount) {
        const photo = queue[index];
        if (controller.signal.aborted) return;
        const startedAt = Date.now();
        patchPhoto(photo.id, { state: "cleaning", startedAt, elapsedMs: 0, progress: `Tratando · ${index + 1}/${queue.length}` });
        try {
          const result = await cleanStudioPhoto(photo.file, {
            watermarkAuthorized,
            signal: controller.signal,
            onProgress: ({ stage }) => patchPhoto(photo.id, {
              state: "cleaning",
              progress: progressLabels[stage] || "Tratando foto"
            })
          });
          const outputUrl = URL.createObjectURL(result.blob);
          urlsRef.current.add(outputUrl);
          const current = photosRef.current.find((item) => item.id === photo.id);
          if (current?.outputUrl) {
            URL.revokeObjectURL(current.outputUrl);
            urlsRef.current.delete(current.outputUrl);
          }
          const elapsedMs = Date.now() - startedAt;
          patchPhoto(photo.id, {
            output: result.blob,
            outputUrl,
            proof: result.proof,
            elapsedMs,
            startedAt: undefined,
            state: "cleaning",
            progress: "Arquivando"
          });
          try {
            await saveStudioSessionPhoto(activeSessionId, {
              source: photo.file,
              output: result.blob,
              elapsedMs,
              proof: result.proof
            });
            patchPhoto(photo.id, { archived: true, state: "cleaned", progress: "Concluída", error: "" });
          } catch (archiveReason) {
            const archiveError = archiveReason instanceof Error ? archiveReason.message : "Não foi possível arquivar a foto.";
            patchPhoto(photo.id, {
              archived: false,
              state: "cleaned",
              progress: "Concluída · não arquivada",
              error: archiveError
            });
            setMessage("Uma foto foi tratada, mas não pôde ser adicionada ao histórico.");
          }
        } catch (reason) {
          if (controller.signal.aborted) return;
          const error = reason instanceof Error ? reason.message : "Não foi possível tratar esta foto.";
          patchPhoto(photo.id, {
            state: "failed",
            startedAt: undefined,
            elapsedMs: Date.now() - startedAt,
            progress: "Falhou",
            error
          });
        }
      }
    }));
    if (mountedRef.current) {
      setBusy(false);
      batchRef.current = null;
    }
  }

  async function exportAll() {
    const cleaned = photosRef.current.filter((photo) => photo.state === "cleaned" && photo.output);
    if (!cleaned.length || exporting) return;
    setExporting(true);
    setMessage("");
    try {
      const zip = await createZip(cleaned.map((photo, index) => ({
        name: cleanedFilename(photo.file.name, index),
        blob: photo.output!
      })));
      downloadZip(zip);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Não foi possível preparar o download.");
    } finally {
      setExporting(false);
    }
  }

  const cleanedCount = photos.filter((photo) => photo.state === "cleaned").length;
  const failedCount = photos.filter((photo) => photo.state === "failed").length;
  const pendingCount = photos.length - cleanedCount;

  if (view === "settings") {
    return (
      <div className="studio-shell">
        <AppHeader user={user} onLogout={onLogout} />
        <StudioSettings onBack={() => setView("photos")} />
      </div>
    );
  }

  if (view === "dashboard") {
    return (
      <div className="studio-shell">
        <AppHeader user={user} onLogout={onLogout} />
        <StudioDashboard onBack={() => setView("photos")} />
      </div>
    );
  }

  if (view === "sessions") {
    return (
      <div className="studio-shell">
        <AppHeader user={user} onLogout={onLogout} />
        <StudioSessions onBack={() => setView("photos")} />
      </div>
    );
  }

  const selectedPhoto = photos.find((photo) => photo.id === selectedPhotoId && photo.state === "cleaned" && photo.outputUrl);

  return (
    <div className="studio-shell">
      <AppHeader user={user} onLogout={onLogout} />
      <main className="studio" data-current-session-id={currentSessionId || ""}>
        <div className="studio__nav-row">
          <button className="module-back" onClick={onBack}><ArrowLeft size={16} /> Início</button>
          <div className="studio__nav-actions">
            <button className="studio-settings-button" type="button" onClick={() => setView("sessions")} aria-label="Sessões do Studio">
              <History size={20} />
            </button>
            <button className="studio-settings-button" type="button" onClick={() => setView("dashboard")} aria-label="Dashboard do Studio">
              <LayoutDashboard size={20} />
            </button>
            <button className="studio-settings-button" type="button" onClick={() => setView("settings")} aria-label="Configurações do Studio">
              <Settings size={20} />
            </button>
          </div>
        </div>
        <div className="studio__heading">
          <div>
            <p className="eyebrow">TRATAMENTO DE IMAGENS</p>
            <h1>Studio</h1>
            <p>Prepare as fotos dos imóveis em um único lote.</p>
          </div>
          <span className="studio__limit">{photos.length}/{MAX_PHOTOS}</span>
        </div>

        <div
          className={`studio-drop ${photos.length ? "studio-drop--compact" : ""} ${dragging ? "is-dragging" : ""}`}
          role="button"
          tabIndex={busy ? -1 : 0}
          aria-disabled={busy}
          onClick={() => !busy && inputRef.current?.click()}
          onKeyDown={(event) => {
            if (!busy && (event.key === "Enter" || event.key === " ")) {
              event.preventDefault();
              inputRef.current?.click();
            }
          }}
          onDragEnter={(event) => { event.preventDefault(); if (!busy) setDragging(true); }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            event.preventDefault();
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            addFiles(event.dataTransfer.files);
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/avif"
            multiple
            hidden
            onChange={(event) => {
              if (event.target.files) addFiles(event.target.files);
              event.target.value = "";
            }}
          />
          <span className="studio-drop__icon"><UploadCloud size={28} /></span>
          <div>
            <strong>{photos.length ? "Adicionar mais fotos" : "Arraste suas fotos aqui"}</strong>
            <small>ou clique para selecionar · JPEG, PNG, WebP ou AVIF</small>
          </div>
        </div>

        {message && <p className="studio-message" role="status">{message}</p>}

        {photos.length > 0 && (
          <section className="studio-grid" aria-label="Fotos selecionadas">
            {photos.map((photo) => (
              <article
                className={`studio-photo studio-photo--${photo.state}`}
                key={photo.id}
                title={photo.error || photo.file.name}
                data-output-type={photo.output?.type || ""}
                data-output-bytes={photo.output?.size || 0}
                data-usage-complete={photo.proof?.usage?.complete === true}
                data-elapsed-ms={photo.startedAt ? Math.max(0, clock - photo.startedAt) : photo.elapsedMs}
                data-archived={photo.archived === true}
                role={photo.state === "cleaned" ? "button" : undefined}
                tabIndex={photo.state === "cleaned" ? 0 : -1}
                onClick={() => photo.state === "cleaned" && setSelectedPhotoId(photo.id)}
                onKeyDown={(event) => {
                  if (photo.state === "cleaned" && (event.key === "Enter" || event.key === " ")) {
                    event.preventDefault();
                    setSelectedPhotoId(photo.id);
                  }
                }}
              >
                <img src={photo.outputUrl || photo.sourceUrl} alt={photo.file.name} />
                <span className="studio-photo__timer">
                  <Clock3 aria-hidden="true" size={13} />
                  <span className="studio-photo__timer-value">
                    {formatStudioElapsed(photo.startedAt ? Math.max(0, clock - photo.startedAt) : photo.elapsedMs)}
                  </span>
                </span>
                <button
                  type="button"
                  className="studio-photo__remove"
                  onClick={(event) => { event.stopPropagation(); removePhoto(photo.id); }}
                  disabled={busy}
                  aria-label={`Remover ${photo.file.name}`}
                >
                  <X size={15} />
                </button>
                <span className="studio-photo__state">
                  {photo.state === "cleaning" || photo.state === "queued" ? <LoaderCircle size={14} className="studio-spinner" /> : photo.state === "cleaned" ? <Check size={14} /> : null}
                  {photo.progress}
                </span>
              </article>
            ))}
          </section>
        )}
      </main>

      <footer className="studio-bar">
        <div className="studio-bar__inner">
          <div className="studio-bar__summary">
            <strong>{photos.length ? `${cleanedCount} concluída${cleanedCount === 1 ? "" : "s"}` : "Nenhuma foto"}</strong>
            <small>{failedCount ? `${failedCount} com erro` : photos.length ? `${pendingCount} pendente${pendingCount === 1 ? "" : "s"}` : "Até 50 imagens"}</small>
          </div>
          <label className="studio-consent">
            <input type="checkbox" checked={watermarkAuthorized} onChange={(event) => setWatermarkAuthorized(event.target.checked)} disabled={busy} />
            <span>Autorizo remover marcas d’água destas fotos</span>
          </label>
          <div className="studio-bar__actions">
            <button className="button button--quiet studio-remove-all" onClick={removeAll} disabled={busy || !photos.length}><Trash2 size={17} /> Remover</button>
            <button className="button button--secondary" onClick={() => void exportAll()} disabled={busy || exporting || !cleanedCount}><Download size={17} /> Baixar</button>
            <button className="button button--primary" onClick={() => void cleanAll()} disabled={busy || !photos.some((photo) => photo.state === "ready" || photo.state === "failed")}>
              {busy ? <LoaderCircle size={17} className="studio-spinner" /> : <Sparkles size={17} />}
              {busy ? "Tratando" : "Tratar fotos"}
            </button>
          </div>
        </div>
      </footer>
      {selectedPhoto?.outputUrl && (
        <StudioCompareModal
          name={selectedPhoto.file.name}
          sourceUrl={selectedPhoto.sourceUrl}
          outputUrl={selectedPhoto.outputUrl}
          usage={selectedPhoto.proof?.usage}
          sourceBytes={selectedPhoto.file.size}
          outputBytes={selectedPhoto.output?.size || 0}
          elapsedMs={selectedPhoto.elapsedMs}
          onClose={() => setSelectedPhotoId(null)}
        />
      )}
    </div>
  );
}
