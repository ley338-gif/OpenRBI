from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base. Models are added starting Phase 2
    (docs/development.md) — User, Role, Group, Policy, BrowserSession, etc.
    """
