import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { AlertCircle, ArrowRight, LoaderCircle, X } from "lucide-react";
import { titleCase } from "./api";
export function Avatar({
  name,
  color,
  small = false,
}: {
  name: string;
  color?: string;
  small?: boolean;
}) {
  const palette: Record<string, string> = {
    sage: "#dbede3",
    blue: "#e0eef8",
    peach: "#f6e6de",
    lavender: "#ede5f7",
  };
  const background = color && (palette[color] || (/^#[0-9a-f]{6}$/i.test(color) ? color : undefined));
  return (
    <span
      className={`avatar ${small ? "small" : ""}`}
      style={background ? { backgroundColor: background } : undefined}
    >
      {name
        .split(" ")
        .filter(Boolean)
        .slice(0, 2)
        .map((s) => s[0])
        .join("")}
    </span>
  );
}
export function Status({ value }: { value: string }) {
  return (
    <span
      className={`status status-${value.replace(/[_ ]/g, "-").toLowerCase()}`}
    >
      {titleCase(value)}
    </span>
  );
}
export function ArrowLink({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button type="button" className="text-button" onClick={onClick}>
      {children}
      <ArrowRight size={14} />
    </button>
  );
}
export function ErrorMessage({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="error-message" role="alert">
      <AlertCircle size={19} />
      <span>{message}</span>
      {retry ? (
        <button className="text-button" onClick={retry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle size={21} className="spin" />
      Loading workspace…
    </div>
  );
}
export function Empty({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {detail ? <p>{detail}</p> : null}
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    d?.showModal();
    return () => d?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={`modal ${wide ? "wide" : ""}`}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-heading">
        <h2>{title}</h2>
        <button
          type="button"
          className="icon-button"
          aria-label="Close dialog"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function PageHeading({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {action}
    </div>
  );
}
export function Field({
  label,
  children,
  full = false,
}: {
  label: string;
  children: ReactNode;
  full?: boolean;
}) {
  return (
    <label className={`field ${full ? "full" : ""}`}>
      <span>{label}</span>
      {children}
    </label>
  );
}
