import { useEffect } from "react";
import { Download, FileText, X } from "lucide-react";
import type { UploadRef } from "../form/types";

type Props = {
  file: UploadRef;
  onClose: () => void;
};

function fileSize(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function DocumentModal({ file, onClose }: Props) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", close);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", close);
    };
  }, [onClose]);

  const downloadURL = `${file.url}${file.url.includes("?") ? "&" : "?"}download=1`;
  return (
    <div className="document-modal" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="document-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="document-modal-title">
        <header>
          <span><FileText size={20} /></span>
          <div><h2 id="document-modal-title">{file.name}</h2><small>PDF · {fileSize(file.size)}</small></div>
          <a className="button button--secondary" href={downloadURL} download={file.name}><Download size={17} /> Baixar</a>
          <button type="button" onClick={onClose} aria-label="Fechar documento"><X size={20} /></button>
        </header>
        <div className="document-modal__viewer">
          <iframe src={file.url} title={`Visualização de ${file.name}`} />
        </div>
      </section>
    </div>
  );
}
