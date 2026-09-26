import { useEffect } from "react";

interface HelpShortcutOptions {
  helpOpen: boolean;
  tourOpen: boolean;
  modalOpen: boolean;
  setHelp: (open: boolean) => void;
}

/** `?` toggles Help anywhere except inside a text control, and never behind the tour or a modal. */
export function useHelpShortcut({ helpOpen, tourOpen, modalOpen, setHelp }: HelpShortcutOptions) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "?" || tourOpen || modalOpen) return;
      const target = event.target;
      if (target instanceof Element && target.closest('[role="dialog"][aria-modal="true"]')) return;
      if (target instanceof HTMLElement && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable || target.hasAttribute("contenteditable"))) return;
      event.preventDefault();
      setHelp(!helpOpen);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [helpOpen, tourOpen, modalOpen]);
}
