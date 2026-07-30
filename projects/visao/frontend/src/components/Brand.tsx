export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand ${compact ? "brand--compact" : ""}`} aria-label="Visão Vendas">
      <svg className="brand__mark" viewBox="0 0 96 58" aria-hidden="true">
        <path className="brand__arc" d="M5 29C12 11 29 3 46 4 36 10 30 19 30 29H5Z" />
        <path className="brand__arc" d="M91 29C84 11 67 3 50 4 60 10 66 19 66 29h25Z" />
        <circle className="brand__iris" cx="48" cy="29" r="17" />
      </svg>
      <span className="brand__copy"><strong>VISÃO</strong><small>IMÓVEIS</small></span>
    </div>
  );
}
