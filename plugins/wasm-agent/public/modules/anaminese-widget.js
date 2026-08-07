const transcriptEventNames = ['tls-realtime-transcript', 'realuse-transcript'];

function transcriptText(event) {
  const detail = event?.detail;
  if (typeof detail === 'string') return detail.trim();
  return String(detail?.text || detail?.transcript || detail?.chunk || '').trim();
}

class AnamineseWidget extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.active = false;
    this.transcript = '';
    this.onTranscript = this.onTranscript.bind(this);
  }

  connectedCallback() {
    this.render();
    transcriptEventNames.forEach((name) => window.addEventListener(name, this.onTranscript));
  }

  disconnectedCallback() {
    transcriptEventNames.forEach((name) => window.removeEventListener(name, this.onTranscript));
  }

  onTranscript(event) {
    if (!this.active) return;
    this.append(transcriptText(event));
  }

  start() {
    if (this.active) return;
    this.active = true;
    this.render();
    this.dispatchEvent(new CustomEvent('anaminese:start', { bubbles: true, composed: true }));
  }

  stop() {
    if (!this.active) return;
    this.active = false;
    this.render();
    this.dispatchEvent(new CustomEvent('anaminese:stop', { bubbles: true, composed: true }));
  }

  append(text) {
    if (!text) return;
    this.transcript += `${this.transcript ? '\n' : ''}${text}`;
    this.render();
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; height:100%; color:#e5e7eb; background:#0f172a; font:14px/1.5 system-ui,sans-serif }
        main { box-sizing:border-box; display:flex; flex-direction:column; gap:12px; height:100%; min-height:240px; padding:16px }
        header { display:flex; align-items:center; justify-content:space-between; gap:12px }
        h2 { margin:0; font-size:16px }
        button { border:0; border-radius:9px; padding:9px 13px; color:white; background:${this.active ? '#dc2626' : '#2563eb'}; cursor:pointer; font-weight:650 }
        pre { box-sizing:border-box; flex:1; overflow:auto; margin:0; padding:12px; white-space:pre-wrap; border:1px solid #334155; border-radius:10px; background:#020617; color:#f8fafc }
        .empty { color:#94a3b8 }
      </style>
      <main>
        <header><h2>Anaminese</h2><button type="button">${this.active ? 'Stop transcription' : 'Start transcription'}</button></header>
        <pre aria-live="polite" class="${this.transcript ? '' : 'empty'}">${this.transcript || 'Transcript will appear here.'}</pre>
      </main>`;
    this.shadowRoot.querySelector('button').addEventListener('click', () => {
      if (this.active) this.stop();
      else this.start();
    });
  }

  getTranscript() { return this.transcript; }

  close() {
    this.stop();
    this.remove();
  }
}

if (!customElements.get('anaminese-widget')) customElements.define('anaminese-widget', AnamineseWidget);

export async function mount({ host, mountRoot } = {}) {
  if (!mountRoot) throw new Error('Anaminese mount root is unavailable.');
  const element = document.createElement('anaminese-widget');
  host?.classList.add('anaminese-widget-host');
  mountRoot.replaceChildren(element);
  return {
    start: () => element.start(),
    stop: () => element.stop(),
    append: (text) => element.append(text),
    getTranscript: () => element.getTranscript(),
    close: () => {
      element.close();
      host?.classList.remove('anaminese-widget-host');
    },
  };
}

export { AnamineseWidget };
