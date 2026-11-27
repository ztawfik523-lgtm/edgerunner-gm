import { useEffect, useRef } from "react";

/**
 * Dialog focus management: while `open`, moves focus into the dialog (unless an
 * element inside it already has focus, e.g. via autoFocus), closes on Escape
 * anywhere in the window, and restores focus to the previously focused element
 * when the dialog closes or unmounts.
 *
 * Attach the returned ref to the dialog container and give it `tabIndex={-1}`.
 * Pass `onClose` as undefined for blocking dialogs that must not close on Escape.
 */
export function useModalFocus<T extends HTMLElement = HTMLDivElement>(
  open: boolean,
  onClose?: () => void,
) {
  const dialogRef = useRef<T | null>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    if (dialog && !dialog.contains(document.activeElement)) {
      dialog.focus();
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && onCloseRef.current) {
        e.preventDefault();
        onCloseRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
    };
  }, [open]);

  return dialogRef;
}
