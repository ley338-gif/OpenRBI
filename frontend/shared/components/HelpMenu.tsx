import { Icons } from "./Icons";
import { useEffect, useState } from "react";
import { useDropdown } from "../hooks/useDropdown";
import { DOCUMENTATION_EVENT, DocumentationModal, type DocumentationRequest } from "./DocumentationModal";

export interface HelpLink {
  label: string;
  href: string;
}

/** Topbar help entry point. Links point at docs/*.md served directly by
 * nginx (frontend/Dockerfile copies docs/ into the image, frontend/
 * nginx.conf serves *.md as readable text/plain) — real, always-in-sync
 * documentation, never a hardcoded GitHub URL that would 404 on an
 * offline/local deployment. Markdown anchors (#section) don't resolve in
 * a plain-text response, so links go to whole documents rather than
 * fabricating per-topic deep links that would silently land at the top of
 * the file instead of the promised section.
 */
export function HelpMenu({ links }: { links: HelpLink[] }) {
  const { open, setOpen, ref } = useDropdown<HTMLDivElement>();
  const [activeDocument, setActiveDocument] = useState<DocumentationRequest | null>(null);

  useEffect(() => {
    const openDocument = (event: Event) => setActiveDocument((event as CustomEvent<DocumentationRequest>).detail);
    window.addEventListener(DOCUMENTATION_EVENT, openDocument);
    return () => window.removeEventListener(DOCUMENTATION_EVENT, openDocument);
  }, []);

  useEffect(() => {
    const openDocumentationLink = (event: MouseEvent) => {
      const anchor = (event.target as HTMLElement | null)?.closest<HTMLAnchorElement>("a[href]");
      if (!anchor) return;
      const url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin || !url.pathname.startsWith("/docs/")) return;
      event.preventDefault();
      setActiveDocument({ href: `${url.pathname}${url.hash}`, label: anchor.textContent?.trim() || "Documentation" });
    };
    document.addEventListener("click", openDocumentationLink);
    return () => document.removeEventListener("click", openDocumentationLink);
  }, []);

  return (
    <div className="dropdown-menu" ref={ref}>
      <button
        type="button"
        className="icon-btn"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Help"
        title="Help"
      >
        <Icons.Help />
      </button>
      {open && (
        <div className="dropdown-panel" role="menu">
          {links.map((link) => (
            <a key={link.href} href={link.href} role="menuitem" onClick={(event) => { event.preventDefault(); setOpen(false); setActiveDocument(link); }}>
              <Icons.Help width={16} height={16} /> {link.label}
            </a>
          ))}
        </div>
      )}
      {activeDocument && <DocumentationModal document={activeDocument} onClose={() => setActiveDocument(null)} />}
    </div>
  );
}
