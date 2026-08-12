# ADR 0010: Docker as the first SandboxProvider, gVisor as an optional additional runtime

## Status

Accepted

## Context

Browser sandboxes need process/filesystem/network isolation between concurrent users on the same host. Docker (via the OCI `runc` runtime) is the ubiquitous baseline; gVisor provides a userspace-kernel sandbox that intercepts syscalls and reduces the attack surface against container-escape vulnerabilities, at some performance cost. Kata Containers and Incus offer VM-level isolation but add substantially more operational complexity.

## Decision

`DockerSandboxProvider` is the first, required `SandboxProvider` implementation for MVP 1, hardened per [docs/security-model.md](../security-model.md) (non-root, dropped capabilities, read-only rootfs, seccomp/AppArmor, resource limits, no host network, no privileged mode, no Docker socket inside the sandbox). `GVisorSandboxProvider` is an optional additional implementation of the same interface, selectable per deployment or per browser node, for operators who want the extra syscall-interception boundary and can accept its performance trade-offs. `KataSandboxProvider`/`IncusSandboxProvider` are documented as possible future providers, not built now.

## Alternatives Considered

- **gVisor-only from the start** — stronger isolation by default, but adds a runtime dependency and potential compatibility/performance issues (e.g. with GPU-accelerated rendering or certain syscalls Firefox needs) that would risk destabilizing the MVP's core end-to-end flow. Kept optional instead of mandatory.
- **Kata Containers (VM-level isolation) for MVP 1** — stronger isolation than either Docker or gVisor, but VM-per-session is a heavier operational model (nested virtualization requirements, slower session start) than justified for a single-host MVP; documented as a later provider option instead.

## Consequences

MVP 1 ships with the security properties Docker + hardening flags can realistically provide, clearly documented as a residual risk in [docs/threat-model.md](../threat-model.md) (container-escape zero-days are an explicit non-goal to fully defend against). Deployments with stricter isolation requirements can opt into `GVisorSandboxProvider` once implemented without any change to session/policy logic, because both providers satisfy the same `SandboxProvider` interface.
