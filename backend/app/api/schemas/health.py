from pydantic import BaseModel

from app.services.health import ComponentHealth, SystemHealth


class ComponentHealthResponse(BaseModel):
    name: str
    status: str
    detail: str | None

    @classmethod
    def from_model(cls, component: ComponentHealth) -> "ComponentHealthResponse":
        return cls(name=component.name, status=component.status.value, detail=component.detail)


class SystemHealthResponse(BaseModel):
    status: str
    components: list[ComponentHealthResponse]

    @classmethod
    def from_model(cls, health: SystemHealth) -> "SystemHealthResponse":
        return cls(
            status=health.status.value,
            components=[ComponentHealthResponse.from_model(c) for c in health.components],
        )
