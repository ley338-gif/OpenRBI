"""Immutable release metadata injected by the image build."""

import os
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version


def _installed_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "0.0.0+unknown"


@dataclass(frozen=True)
class BuildInfo:
    version: str
    commit_sha: str
    build_date: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


BUILD_INFO = BuildInfo(
    version=os.getenv("OPENRBI_VERSION", _installed_version("openrbi-session-agent")),
    commit_sha=os.getenv("OPENRBI_COMMIT_SHA", "unknown"),
    build_date=os.getenv("OPENRBI_BUILD_DATE", "unknown"),
)
