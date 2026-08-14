import { Fragment, useEffect, useState, type ReactNode } from "react";
import { Icons } from "./Icons";

export const DOCUMENTATION_EVENT = "openrbi:open-documentation";

export interface DocumentationRequest {
  label: string;
  href: string;
}

export function openDocumentation(request: DocumentationRequest) {
  window.dispatchEvent(new CustomEvent<DocumentationRequest>(DOCUMENTATION_EVENT, { detail: request }));
}

export function DocumentationLink({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return <a href={href} className={className} onClick={(event) => { event.preventDefault(); openDocumentation({ href, label: typeof children === "string" ? children : "Documentation" }); }}>{children}</a>;
}

export function DocumentationModal({ document, onClose }: { document: DocumentationRequest; onClose: () => void }) {
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const isPdf = document.href.toLowerCase().split(/[?#]/)[0].endsWith(".pdf");

  useEffect(() => {
    if (isPdf) return;
    const controller = new AbortController();
    setContent("");
    setError("");
    fetch(document.href, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.text(); })
      .then(setContent)
      .catch((reason) => { if (reason instanceof Error && reason.name !== "AbortError") setError("The documentation could not be loaded."); });
    return () => controller.abort();
  }, [document.href, isPdf]);

  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);

  return <div className="modal-overlay documentation-overlay" onClick={onClose}>
    <section className="modal documentation-modal" role="dialog" aria-modal="true" aria-labelledby="documentation-title" onClick={(event) => event.stopPropagation()}>
      <header className="documentation-header"><div><span className="documentation-eyebrow">OpenRBI Manual</span><h2 id="documentation-title">{document.label}</h2></div><div className="documentation-header-actions"><a className="btn btn-secondary btn-sm" href={document.href} target="_blank" rel="noreferrer">Open separately <Icons.ExternalLink /></a><button type="button" className="icon-btn" onClick={onClose} aria-label="Close documentation" title="Close">×</button></div></header>
      <div className="documentation-body">
        {isPdf ? <iframe className="documentation-pdf" src={document.href} title={document.label} /> : error ? <div className="documentation-error"><Icons.Incident /><strong>{error}</strong><a href={document.href} target="_blank" rel="noreferrer">Open the original document</a></div> : !content ? <div className="documentation-loading"><span className="spinner" /> Loading manual…</div> : <MarkdownDocument source={content} baseHref={document.href} />}
      </div>
    </section>
  </div>;
}

function MarkdownDocument({ source, baseHref }: { source: string; baseHref: string }) {
  const lines = source.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    if (line.startsWith("```")) {
      const language = line.slice(3).trim(); const code: string[] = []; index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) { code.push(lines[index]); index += 1; }
      blocks.push(<pre key={`code-${index}`}><code data-language={language}>{code.join("\n")}</code></pre>); index += 1; continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) { const level = heading[1].length; const text = heading[2]; const id = slug(text); blocks.push(level === 1 ? <h1 id={id} key={index}>{inline(text, baseHref)}</h1> : level === 2 ? <h2 id={id} key={index}>{inline(text, baseHref)}</h2> : level === 3 ? <h3 id={id} key={index}>{inline(text, baseHref)}</h3> : <h4 id={id} key={index}>{inline(text, baseHref)}</h4>); index += 1; continue; }
    if (/^>\s?/.test(line)) { const quote: string[] = []; while (index < lines.length && /^>\s?/.test(lines[index])) { quote.push(lines[index].replace(/^>\s?/, "")); index += 1; } blocks.push(<blockquote key={`quote-${index}`}>{inline(quote.join(" "), baseHref)}</blockquote>); continue; }
    if (/^[-*]\s+/.test(line)) { const items: string[] = []; while (index < lines.length && /^[-*]\s+/.test(lines[index])) { items.push(lines[index].replace(/^[-*]\s+/, "")); index += 1; } blocks.push(<ul key={`list-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inline(item, baseHref)}</li>)}</ul>); continue; }
    if (/^\d+\.\s+/.test(line)) { const items: string[] = []; while (index < lines.length && /^\d+\.\s+/.test(lines[index])) { items.push(lines[index].replace(/^\d+\.\s+/, "")); index += 1; } blocks.push(<ol key={`ordered-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inline(item, baseHref)}</li>)}</ol>); continue; }
    if (line.includes("|") && index + 1 < lines.length && /^\s*\|?\s*:?-+/.test(lines[index + 1])) {
      const rows: string[][] = [splitTable(line)]; index += 2;
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) { rows.push(splitTable(lines[index])); index += 1; }
      blocks.push(<div className="documentation-table-wrap" key={`table-${index}`}><table><thead><tr>{rows[0].map((cell, cellIndex) => <th key={cellIndex}>{inline(cell, baseHref)}</th>)}</tr></thead><tbody>{rows.slice(1).map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{inline(cell, baseHref)}</td>)}</tr>)}</tbody></table></div>); continue;
    }
    if (/^---+$/.test(line.trim())) { blocks.push(<hr key={index} />); index += 1; continue; }
    const paragraph = [line]; index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,4})\s|^```|^>|^[-*]\s+|^\d+\.\s+/.test(lines[index])) { paragraph.push(lines[index]); index += 1; }
    blocks.push(<p key={`paragraph-${index}`}>{inline(paragraph.join(" "), baseHref)}</p>);
  }
  return <article className="documentation-article">{blocks}</article>;
}

function inline(text: string, baseHref: string): ReactNode[] {
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  return text.split(pattern).filter(Boolean).map((part, index) => {
    if (part.startsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link) return <a key={index} href={resolveHref(link[2], baseHref)} target={link[2].startsWith("http") ? "_blank" : undefined} rel="noreferrer">{link[1]}</a>;
    return <Fragment key={index}>{part}</Fragment>;
  });
}

function resolveHref(href: string, baseHref: string) { if (/^(https?:|\/|#)/.test(href)) return href; const base = baseHref.slice(0, baseHref.lastIndexOf("/") + 1); return `${base}${href}`; }
function splitTable(line: string) { return line.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((cell) => cell.trim()); }
function slug(text: string) { return text.toLowerCase().replace(/[^a-z0-9\s-]/g, "").trim().replace(/\s+/g, "-"); }
