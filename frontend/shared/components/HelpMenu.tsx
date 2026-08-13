import { Icons } from "./Icons";
import { useDropdown } from "../hooks/useDropdown";

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
            <a key={link.href} href={link.href} target="_blank" rel="noreferrer" role="menuitem" onClick={() => setOpen(false)}>
              <Icons.ExternalLink width={16} height={16} /> {link.label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
