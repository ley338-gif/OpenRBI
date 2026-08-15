# ADR 0009: noVNC as the first DisplayProvider

## Status

Accepted

## Context

The remote browser's display must reach the user's own browser with no native client install, ideally over a protocol that is easy to proxy through the reverse proxy and easy to audit. Candidates include noVNC (pure web VNC client), KasmVNC (VNC fork with web-native extensions, e.g. clipboard/audio), and Apache Guacamole (protocol-agnostic remote desktop gateway supporting VNC/RDP/SSH).

## Decision

MVP 1 uses noVNC as the `DisplayProvider` implementation: Debian's `x11vnc 0.9.16-9` runs inside the browser container against an Xvfb display, and noVNC's web client connects to it through the reverse proxy over a WebSocket tunnel. Exact release dependencies are recorded in [DEPENDENCIES.md](../../DEPENDENCIES.md). This is implemented behind the `DisplayProvider` interface (see [ADR 0003](0003-provider-abstraction.md)) specifically so it is not deeply coupled into session/core logic.

## Alternatives Considered

- **KasmVNC** — offers useful built-in extensions (multi-user awareness, clipboard handling, better performance) but is a more specialized fork; the project's own constraints explicitly warn against coupling third-party display forks deeply into core logic. Left as a documented future `DisplayProvider` alternative.
- **Apache Guacamole** — more general (multi-protocol) but adds its own guacd proxy daemon and a heavier deployment footprint than MVP 1 needs for a single browser-display use case.

## Consequences

noVNC is simple, widely used, and easy to reason about from a security-review standpoint (plain VNC protocol, thin JS client). Because it's behind `DisplayProvider`, swapping in KasmVNC or Guacamole later for richer functionality (e.g. file-clipboard, audio) does not require changing session lifecycle or policy code — only a new provider implementation and its own hardening pass.
