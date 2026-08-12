import asyncio

import docker
from docker.errors import NotFound

from app.providers.base import (
    SandboxConfig,
    SandboxDisplayInfo,
    SandboxMetrics,
    SandboxProvider,
    SandboxRuntimeStatus,
    SandboxStatus,
)

_MANAGED_LABEL = "openrbi.managed"
_SESSION_LABEL = "openrbi.session_id"
_NETWORK_LABEL = "openrbi.network"
_VNC_PORT = 5900


def _container_name(session_id: str) -> str:
    return f"openrbi-session-{session_id}"


class DockerSandboxProvider:
    """First required SandboxProvider implementation (docs/adr/0010). Only
    ever creates/inspects/acts on containers carrying the openrbi.managed
    label with a matching session id — never touches arbitrary containers
    on the host, even if handed an unexpected session id.

    docker-py is a blocking SDK; every call is pushed through
    asyncio.to_thread so it doesn't block the FastAPI event loop.
    """

    def __init__(self, base_url: str) -> None:
        self._client = docker.DockerClient(base_url=base_url)

    async def create_session(self, session_id: str, config: SandboxConfig) -> None:
        await asyncio.to_thread(self._create_session_sync, session_id, config)

    def _create_session_sync(self, session_id: str, config: SandboxConfig) -> None:
        name = _container_name(session_id)
        try:
            existing = self._client.containers.get(name)
            if existing.labels.get(_MANAGED_LABEL) != "true":
                raise RuntimeError(f"container name collision with an unmanaged container: {name}")
            return  # idempotent: already created
        except NotFound:
            pass

        labels = {
            _MANAGED_LABEL: "true",
            _SESSION_LABEL: session_id,
            _NETWORK_LABEL: config.network_name,
            **config.labels,
        }

        # Baseline hardening (docs/security-model.md#sandbox-model). Browser-
        # specific profile/tmpfs paths and seccomp/AppArmor profiles are
        # layered on in Phase 7/20 once the real browser image exists —
        # this provider is generic over `config.image`.
        self._client.containers.create(
            image=config.image,
            name=name,
            command=config.command,
            labels=labels,
            user="10001:10001",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            read_only=True,
            tmpfs={"/tmp": f"size={config.disk_limit_mb}m"},
            mem_limit=f"{config.ram_limit_mb}m",
            nano_cpus=int(config.cpu_limit * 1_000_000_000),
            pids_limit=config.pid_limit,
            network=config.network_name,
            network_disabled=False,
            detach=True,
        )

    async def start_session(self, session_id: str) -> None:
        await asyncio.to_thread(self._start_session_sync, session_id)

    def _start_session_sync(self, session_id: str) -> None:
        container = self._get_managed_container(session_id)
        container.reload()
        if container.status != "running":
            container.start()

    async def isolate_session(self, session_id: str) -> None:
        await asyncio.to_thread(self._isolate_session_sync, session_id)

    def _isolate_session_sync(self, session_id: str) -> None:
        """Disconnects the container from every network it's attached to —
        network egress DENY ALL regardless of topology, which is the one
        piece of "isolate" (docs/session-lifecycle.md) enforceable at this
        layer. Clipboard/upload/download denial is enforced by the display
        layer and file gateway (Phase 8/13/16), not here.
        """
        container = self._get_managed_container(session_id)
        container.reload()
        for network_name in container.attrs.get("NetworkSettings", {}).get("Networks", {}):
            self._client.networks.get(network_name).disconnect(container, force=True)

    async def restore_session(self, session_id: str) -> None:
        await asyncio.to_thread(self._restore_session_sync, session_id)

    def _restore_session_sync(self, session_id: str) -> None:
        container = self._get_managed_container(session_id)
        network_name = container.labels.get(_NETWORK_LABEL)
        if not network_name:
            raise RuntimeError(f"session {session_id} has no recorded network to restore")
        container.reload()
        attached = container.attrs.get("NetworkSettings", {}).get("Networks", {})
        if network_name not in attached:
            self._client.networks.get(network_name).connect(container)

    async def terminate_session(self, session_id: str) -> None:
        await asyncio.to_thread(self._terminate_session_sync, session_id)

    def _terminate_session_sync(self, session_id: str) -> None:
        """Idempotent per docs/session-lifecycle.md: terminating an
        already-terminated (or never-created) session succeeds rather than
        erroring.
        """
        try:
            container = self._client.containers.get(_container_name(session_id))
        except NotFound:
            return
        if container.labels.get(_MANAGED_LABEL) != "true":
            raise RuntimeError(f"refusing to remove an unmanaged container: {_container_name(session_id)}")
        container.remove(force=True)

    async def get_status(self, session_id: str) -> SandboxStatus:
        return await asyncio.to_thread(self._get_status_sync, session_id)

    def _get_status_sync(self, session_id: str) -> SandboxStatus:
        try:
            container = self._get_managed_container(session_id)
        except NotFound:
            return SandboxStatus(status=SandboxRuntimeStatus.NOT_FOUND)

        container.reload()
        docker_status = container.status  # created, running, paused, exited, dead, restarting
        networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})

        if docker_status == "running" and not networks:
            status = SandboxRuntimeStatus.ISOLATED
        elif docker_status == "running":
            status = SandboxRuntimeStatus.RUNNING
        elif docker_status == "created":
            status = SandboxRuntimeStatus.CREATED
        elif docker_status in ("exited", "dead"):
            status = SandboxRuntimeStatus.EXITED
        else:
            status = SandboxRuntimeStatus.ERROR

        started_at = container.attrs.get("State", {}).get("StartedAt")
        return SandboxStatus(status=status, container_id=container.id, started_at=started_at, detail=docker_status)

    async def get_metrics(self, session_id: str) -> SandboxMetrics:
        return await asyncio.to_thread(self._get_metrics_sync, session_id)

    def _get_metrics_sync(self, session_id: str) -> SandboxMetrics:
        container = self._get_managed_container(session_id)
        stats = container.stats(stream=False)

        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"].get("system_cpu_usage", 0) - stats["precpu_stats"].get(
            "system_cpu_usage", 0
        )
        online_cpus = stats["cpu_stats"].get("online_cpus") or len(
            stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])
        )
        cpu_percent = (cpu_delta / system_delta) * online_cpus * 100 if system_delta > 0 else 0.0

        mem_usage = stats.get("memory_stats", {}).get("usage", 0)
        mem_limit = stats.get("memory_stats", {}).get("limit", 0)
        pids = stats.get("pids_stats", {}).get("current", 0)

        return SandboxMetrics(
            cpu_percent=round(cpu_percent, 2),
            memory_usage_mb=round(mem_usage / (1024 * 1024), 2),
            memory_limit_mb=round(mem_limit / (1024 * 1024), 2),
            pids=pids,
        )

    async def get_display_info(self, session_id: str) -> SandboxDisplayInfo:
        return await asyncio.to_thread(self._get_display_info_sync, session_id)

    def _get_display_info_sync(self, session_id: str) -> SandboxDisplayInfo:
        """Returns the container's IP on its recorded network so the control
        plane can open a data-plane TCP connection to the VNC port it
        exposes. This is not a privileged operation — the backend still
        never touches the Docker socket (docs/adr/0005) — it's a plain
        outbound connection to a port the container already listens on.
        """
        container = self._get_managed_container(session_id)
        network_name = container.labels.get(_NETWORK_LABEL)
        container.reload()
        networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
        network = networks.get(network_name)
        if not network or not network.get("IPAddress"):
            raise RuntimeError(f"session {session_id} has no address on network {network_name}")
        return SandboxDisplayInfo(host=network["IPAddress"], port=_VNC_PORT)

    async def count_active_sessions(self) -> int:
        return await asyncio.to_thread(self._count_active_sessions_sync)

    def _count_active_sessions_sync(self) -> int:
        containers = self._client.containers.list(filters={"label": f"{_MANAGED_LABEL}=true"})
        return len(containers)

    async def runtime_version(self) -> str:
        return await asyncio.to_thread(lambda: self._client.version().get("Version", "unknown"))

    def _get_managed_container(self, session_id: str):
        container = self._client.containers.get(_container_name(session_id))
        if container.labels.get(_MANAGED_LABEL) != "true" or container.labels.get(_SESSION_LABEL) != session_id:
            raise RuntimeError(f"container for session {session_id} is not OpenRBI-managed")
        return container
