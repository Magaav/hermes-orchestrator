import { useEffect, useRef, useState } from "react";
import { Camera, ChevronDown, LoaderCircle, LogOut, ShieldCheck, X } from "lucide-react";
import type { SessionUser } from "../form/api";
import { uploadProfilePicture } from "../profile/api";
import { Brand } from "./Brand";

type Props = {
  user: SessionUser | null;
  onLogout: () => void;
};

export function AppHeader({ user, onLogout }: Props) {
  const pictureKey = user ? `visao-profile-picture-${user.id}` : "";
  const [open, setOpen] = useState(false);
  const [picture, setPicture] = useState(() => pictureKey ? sessionStorage.getItem(pictureKey) || user?.picture || "" : user?.picture || "");
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setPicture(pictureKey ? sessionStorage.getItem(pictureKey) || user?.picture || "" : user?.picture || "");
  }, [pictureKey, user?.picture]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", close);
    };
  }, [open]);

  async function changePicture(file?: File) {
    if (!file) return;
    setUploading(true);
    setMessage("");
    try {
      const result = await uploadProfilePicture(file);
      setPicture(result.picture);
      if (pictureKey) sessionStorage.setItem(pictureKey, result.picture);
      setMessage("Foto atualizada.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Não foi possível atualizar a foto.");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <header className="topbar">
      <Brand compact />
      <div className="topbar__user">
        <button className="topbar__profile-trigger" type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-expanded={open}>
          {picture ? <img className="topbar__avatar" src={picture} alt="" referrerPolicy="no-referrer" onError={() => setPicture("")} /> : <span className="topbar__avatar">{user?.name?.slice(0, 1).toUpperCase() || "V"}</span>}
          <div><strong>{user?.name || "Visão"}</strong><small>{user?.email}</small></div>
          <ChevronDown size={15} />
        </button>
      </div>
      {open && (
        <div className="profile-modal" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
          <section className="profile-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="profile-modal-title">
            <button className="profile-modal__close" type="button" onClick={() => setOpen(false)} aria-label="Fechar"><X size={18} /></button>
            <div className="profile-modal__photo">
              {picture ? <img src={picture} alt="" referrerPolicy="no-referrer" onError={() => setPicture("")} /> : <span>{user?.name?.slice(0, 1).toUpperCase() || "V"}</span>}
              <button type="button" disabled={uploading} onClick={() => inputRef.current?.click()} aria-label="Alterar foto">
                {uploading ? <LoaderCircle className="studio-spinner" size={18} /> : <Camera size={18} />}
              </button>
              <input ref={inputRef} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(event) => void changePicture(event.target.files?.[0])} />
            </div>
            <div className="profile-modal__identity">
              <h2 id="profile-modal-title">{user?.name || "Usuário"}</h2>
              <p>{user?.email}</p>
            </div>
            <div className="profile-modal__roles">
              <span><ShieldCheck size={16} /> Cargo</span>
              <div>{user?.roles?.length ? user.roles.map((role) => <b key={role}>{role}</b>) : <b>Membro</b>}</div>
            </div>
            {message && <p className="profile-modal__message" role="status">{message}</p>}
            <button className="button profile-modal__logout" type="button" onClick={onLogout}><LogOut size={17} /> Sair</button>
          </section>
        </div>
      )}
    </header>
  );
}
