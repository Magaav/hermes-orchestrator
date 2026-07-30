import { useEffect, useState } from "react";
import { Coins, X } from "lucide-react";
import type { StudioTokenUsage } from "../studio/api";
import { formatStudioElapsed } from "../studio/time";

type Props = {
  name: string;
  sourceUrl: string;
  outputUrl: string;
  usage?: StudioTokenUsage;
  sourceBytes: number;
  outputBytes: number;
  elapsedMs?: number;
  onClose: () => void;
};

const numberFormat = new Intl.NumberFormat("pt-BR");
const byteFormat = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${byteFormat.format(value / 1024)} KB`;
  return `${byteFormat.format(value / (1024 * 1024))} MB`;
}

export function StudioCompareModal({ name, sourceUrl, outputUrl, usage, sourceBytes, outputBytes, elapsedMs, onClose }: Props) {
  const [view, setView] = useState<"before" | "after">("after");

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [onClose]);

  const mainTokens = (usage?.main_input_tokens || 0) + (usage?.main_output_tokens || 0);
  const imageTokens = (usage?.image_input_tokens || 0) + (usage?.image_output_tokens || 0);

  return (
    <div
      className="studio-modal"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="studio-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="studio-compare-title">
        <header className="studio-modal__header">
          <div>
            <p className="eyebrow">COMPARAÇÃO</p>
            <h2 id="studio-compare-title">{name}</h2>
          </div>
          <button type="button" className="studio-modal__close" onClick={onClose} aria-label="Fechar comparação">
            <X size={20} />
          </button>
        </header>

        <div className="studio-modal__switch" aria-label="Escolha a versão da foto">
          <button type="button" className={view === "before" ? "is-active" : ""} onClick={() => setView("before")}>Antes</button>
          <button type="button" className={view === "after" ? "is-active" : ""} onClick={() => setView("after")}>Depois</button>
        </div>

        <div className="studio-modal__image">
          <img src={view === "before" ? sourceUrl : outputUrl} alt={`${view === "before" ? "Antes" : "Depois"} de ${name}`} />
          <span>{view === "before" ? "Antes" : "Depois"}</span>
        </div>

        <aside className="studio-modal__usage" aria-label="Consumo de tokens desta foto">
          <span className="studio-modal__usage-icon"><Coins size={19} /></span>
          <div className="studio-modal__usage-total">
            <small>Consumo desta foto</small>
            <strong>{usage?.available ? numberFormat.format(usage.total_tokens) : "Não informado"}</strong>
            <span>
              {usage?.complete
                ? "tokens reportados · contagem completa"
                : usage?.available
                  ? "contagem parcial · fora das médias"
                  : "O provedor não reportou tokens nesta execução"}
            </span>
          </div>
          {usage?.available && (
            <dl>
              <div><dt>Modelo principal</dt><dd>{usage.main_available ? numberFormat.format(mainTokens) : "Não informado"}</dd></div>
              <div><dt>Geração da imagem</dt><dd>{usage.image_available ? numberFormat.format(imageTokens) : "Não informado"}</dd></div>
            </dl>
          )}
          <p>
            {elapsedMs !== undefined && <>Tempo: {formatStudioElapsed(elapsedMs)} · </>}
            AVIF lossless: {formatBytes(outputBytes)} · original: {formatBytes(sourceBytes)}. Tokens não dependem do tamanho final em KB.
          </p>
        </aside>
      </section>
    </div>
  );
}
