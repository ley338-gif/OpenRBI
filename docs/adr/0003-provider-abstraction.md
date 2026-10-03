# ADR 0003: Provider abstraction for sandbox, display, browser, and scanner

## Status

Accepted. Implementation status (v1.0): only the sandbox seam exists as a formal interface — `SandboxProvider` (`session-agent/app/providers/base.py`) with its single implementation `DockerSandboxProvider`, selected in `session-agent/app/providers/factory.py`. Display (noVNC), browser (the Firefox ESR image) and scanner (`app/core/clamav_client.py`) are concrete integrations behind module boundaries; the `DisplayProvider`/`BrowserProvider`/`FileScanner` interfaces and the named alternative implementations (including `GVisorSandboxProvider`) are not built. See [architecture.md](../architecture.md#provider-architecture).

## Context

MVP 1 commits to specific technologies (Docker, noVNC, Firefox, ClamAV), but the project's stated goal is to support additional/alternative backends later (gVisor, Kata, Incus for sandboxing; KasmVNC, Guacamole for display; Chromium for browser) without being tightly coupled to any one vendor's implementation details, and without rewriting core session/policy logic when a backend changes.

## Decision

Define explicit provider interfaces that all concrete implementations must satisfy:

- `SandboxProvider`: `create_session()`, `start_session()`, `isolate_session()`, `restore_session()`, `terminate_session()`, `get_status()`, `get_metrics()`
- `DisplayProvider`: `prepare()`, `get_connection_info()`, `disconnect()`, `destroy()`
- `BrowserProvider`: browser-specific launch/configuration behind a stable interface
- `FileScanner`: `scan()`, `health()`, `signature_version()`

Core session/policy/quarantine logic depends only on these interfaces, never on Docker SDK calls, noVNC internals, or ClamAV protocol details directly. Concrete providers are injected via configuration.

## Alternatives Considered

- **Direct integration** (call `docker-py` / clamd protocol directly from session/business logic) — faster to write initially, but couples core logic to vendor specifics, makes swapping runtimes (e.g. adding gVisor) a cross-cutting change, and makes unit-testing session logic require a real Docker daemon.

## Consequences

Adds an interface layer to design and maintain, but keeps `DockerSandboxProvider`/`GVisorSandboxProvider`/`NoVNCDisplayProvider`/`FirefoxProvider`/`ClamAVScanner` as swappable, independently testable modules. This also makes it possible to fake providers in tests (e.g. asserting policy decisions without spinning up real containers).
