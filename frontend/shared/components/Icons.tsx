import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function base(children: React.ReactNode, props: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

/** Hand-written, dependency-free icon set (no icon-library install) —
 * one file, reused by both portals' sidebars/topbars/forms.
 */
export const Icons = {
  Dashboard: (p: IconProps) =>
    base(
      <>
        <rect x="3" y="3" width="7" height="9" rx="1.5" />
        <rect x="14" y="3" width="7" height="5" rx="1.5" />
        <rect x="14" y="12" width="7" height="9" rx="1.5" />
        <rect x="3" y="16" width="7" height="5" rx="1.5" />
      </>,
      p,
    ),
  Browser: (p: IconProps) =>
    base(
      <>
        <rect x="3" y="4" width="18" height="13" rx="2" />
        <path d="M8 21h8M12 17v4" />
      </>,
      p,
    ),
  Download: (p: IconProps) =>
    base(
      <>
        <path d="M12 3v12M7 10l5 5 5-5" />
        <path d="M4 20h16" />
      </>,
      p,
    ),
  User: (p: IconProps) =>
    base(
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 20c0-4 3.5-6 8-6s8 2 8 6" />
      </>,
      p,
    ),
  Users: (p: IconProps) =>
    base(
      <>
        <circle cx="9" cy="8" r="3.2" />
        <path d="M3 20c0-3.4 2.7-5.2 6-5.2s6 1.8 6 5.2" />
        <path d="M16 8.2a3 3 0 1 1 0 5.9" />
        <path d="M15 14.8c2.7.4 4.5 2 4.5 5.2" />
      </>,
      p,
    ),
  Groups: (p: IconProps) =>
    base(
      <>
        <rect x="3" y="4" width="8" height="8" rx="1.5" />
        <rect x="13" y="4" width="8" height="8" rx="1.5" />
        <rect x="8" y="14" width="8" height="6" rx="1.5" />
      </>,
      p,
    ),
  Sessions: (p: IconProps) =>
    base(
      <>
        <rect x="3" y="4" width="18" height="12" rx="2" />
        <path d="M9 21h6M12 16v5" />
        <path d="M8 12l2.5-3L13 11l3-3.5" />
      </>,
      p,
    ),
  Shield: (p: IconProps) =>
    base(<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z" />, p),
  Quarantine: (p: IconProps) =>
    base(
      <>
        <path d="M12 3l9 16H3z" />
        <path d="M12 10v4M12 17.5v.1" />
      </>,
      p,
    ),
  Incident: (p: IconProps) =>
    base(
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7.5v5M12 16.2v.1" />
      </>,
      p,
    ),
  Audit: (p: IconProps) =>
    base(
      <>
        <rect x="4" y="3" width="16" height="18" rx="2" />
        <path d="M8 8h8M8 12h8M8 16h5" />
      </>,
      p,
    ),
  System: (p: IconProps) =>
    base(
      <>
        <rect x="3" y="4" width="18" height="6" rx="1.5" />
        <rect x="3" y="14" width="18" height="6" rx="1.5" />
        <path d="M7 7h.01M7 17h.01" />
      </>,
      p,
    ),
  Worker: (p: IconProps) =>
    base(
      <>
        <rect x="6" y="6" width="12" height="12" rx="1.5" />
        <rect x="10" y="10" width="4" height="4" />
        <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2 2M17.1 17.1l2 2M4.9 19.1l2-2M17.1 6.9l2-2" />
      </>,
      p,
    ),
  Search: (p: IconProps) =>
    base(
      <>
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="M20 20l-4.8-4.8" />
      </>,
      p,
    ),
  Logout: (p: IconProps) =>
    base(
      <>
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
        <path d="M16 17l5-5-5-5M21 12H9" />
      </>,
      p,
    ),
  ChevronDown: (p: IconProps) => base(<path d="M6 9l6 6 6-6" />, p),
  ChevronsLeft: (p: IconProps) => base(<path d="M11 17l-5-5 5-5M18 17l-5-5 5-5" />, p),
  ChevronsRight: (p: IconProps) => base(<path d="M13 17l5-5-5-5M6 17l5-5-5-5" />, p),
  Settings: (p: IconProps) =>
    base(
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09a1.65 1.65 0 00-1-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z" />
      </>,
      p,
    ),
  Eye: (p: IconProps) =>
    base(
      <>
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
        <circle cx="12" cy="12" r="3" />
      </>,
      p,
    ),
  EyeOff: (p: IconProps) =>
    base(
      <>
        <path d="M3 3l18 18" />
        <path d="M10.6 5.2C11 5.1 11.5 5 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.4 4.3M6.5 6.6A17 17 0 0 0 2 12s3.5 7 10 7c1 0 1.9-.1 2.7-.4" />
        <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
      </>,
      p,
    ),
  Help: (p: IconProps) =>
    base(
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M9.5 9.3a2.5 2.5 0 1 1 3.7 2.6c-.6.4-1.2.9-1.2 1.9v.3" />
        <path d="M12 17.2v.1" />
      </>,
      p,
    ),
  ExternalLink: (p: IconProps) =>
    base(
      <>
        <path d="M14 4h6v6" />
        <path d="M20 4L10 14" />
        <path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" />
      </>,
      p,
    ),
  Bell: (p: IconProps) =>
    base(
      <>
        <path d="M6 9a6 6 0 1 1 12 0c0 3.2 1 5 2 6H4c1-1 2-2.8 2-6z" />
        <path d="M9.5 19a2.5 2.5 0 0 0 5 0" />
      </>,
      p,
    ),
  Maximize: (p: IconProps) =>
    base(
      <>
        <path d="M8 3H5a2 2 0 0 0-2 2v3" />
        <path d="M16 3h3a2 2 0 0 1 2 2v3" />
        <path d="M8 21H5a2 2 0 0 1-2-2v-3" />
        <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
      </>,
      p,
    ),
  Minimize: (p: IconProps) =>
    base(
      <>
        <path d="M3 9h4a2 2 0 0 0 2-2V3" />
        <path d="M21 9h-4a2 2 0 0 1-2-2V3" />
        <path d="M3 15h4a2 2 0 0 1 2 2v4" />
        <path d="M21 15h-4a2 2 0 0 0-2 2v4" />
      </>,
      p,
    ),
  Clipboard: (p: IconProps) =>
    base(
      <>
        <rect x="6" y="4" width="12" height="17" rx="1.5" />
        <path d="M9 4V3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1" />
      </>,
      p,
    ),
  RefreshCw: (p: IconProps) =>
    base(
      <>
        <path d="M20 11a8 8 0 0 0-14.6-4.6M4 5v5h5" />
        <path d="M4 13a8 8 0 0 0 14.6 4.6M20 19v-5h-5" />
      </>,
      p,
    ),
  File: (p: IconProps) =>
    base(
      <>
        <path d="M6 3h8l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
        <path d="M14 3v4h4" />
      </>,
      p,
    ),
};
