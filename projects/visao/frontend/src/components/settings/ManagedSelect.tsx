import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";

export type ManagedSelectOption = {
  value: string;
  label: string;
  detail?: string;
  color?: string;
};

type Props = {
  ariaLabel: string;
  value: string;
  options: ManagedSelectOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
};

export function ManagedSelect({ ariaLabel, value, options, onChange, disabled = false }: Props) {
  const id = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));
  const selected = options[selectedIndex];
  const openUp = Boolean(rect && rect.bottom + Math.min(260, options.length * 48 + 12) > window.innerHeight && rect.top > window.innerHeight / 2);

  function openMenu() {
    if (disabled || !options.length) return;
    window.dispatchEvent(new CustomEvent("visao-managed-select-open", { detail: id }));
    setRect(triggerRef.current?.getBoundingClientRect() || null);
    setActiveIndex(selectedIndex);
    setOpen(true);
  }

  function closeMenu(focus = false) {
    setOpen(false);
    if (focus) triggerRef.current?.focus();
  }

  function select(index: number) {
    const option = options[index];
    if (!option) return;
    onChange(option.value);
    closeMenu(true);
  }

  useEffect(() => {
    const closePeer = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== id) setOpen(false);
    };
    window.addEventListener("visao-managed-select-open", closePeer);
    return () => window.removeEventListener("visao-managed-select-open", closePeer);
  }, [id]);

  useEffect(() => {
    if (!open) return;
    const update = () => setRect(triggerRef.current?.getBoundingClientRect() || null);
    const closeOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    document.addEventListener("mousedown", closeOutside);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      document.removeEventListener("mousedown", closeOutside);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`)?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, open]);

  function onKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        openMenu();
        return;
      }
      const direction = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((current) => Math.max(0, Math.min(options.length - 1, current + direction)));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open) select(activeIndex);
      else openMenu();
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeMenu(true);
    } else if (event.key === "Home" && open) {
      event.preventDefault();
      setActiveIndex(0);
    } else if (event.key === "End" && open) {
      event.preventDefault();
      setActiveIndex(options.length - 1);
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <div className="managed-select">
      <button
        ref={triggerRef}
        className="managed-select__trigger"
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        disabled={disabled}
        onClick={() => open ? closeMenu() : openMenu()}
        onKeyDown={onKeyDown}
      >
        <span>{selected?.color && <i style={{ background: selected.color }} />}<b>{selected?.label || "Selecione"}</b></span>
        <ChevronDown size={16} />
      </button>
      {open && rect && createPortal(
        <div
          ref={menuRef}
          id={id}
          className="managed-select__menu"
          role="listbox"
          aria-label={ariaLabel}
          style={{
            left: rect.left,
            top: openUp ? "auto" : rect.bottom + 5,
            bottom: openUp ? window.innerHeight - rect.top + 5 : "auto",
            width: rect.width
          }}
        >
          {options.map((option, index) => (
            <button
              key={option.value}
              type="button"
              role="option"
              aria-selected={option.value === value}
              className={index === activeIndex ? "is-active" : ""}
              data-index={index}
              tabIndex={-1}
              onMouseEnter={() => setActiveIndex(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => select(index)}
            >
              <span>{option.color && <i style={{ background: option.color }} />}<b>{option.label}</b>{option.detail && <small>{option.detail}</small>}</span>
              {option.value === value && <Check size={16} />}
            </button>
          ))}
        </div>,
        document.body
      )}
    </div>
  );
}
