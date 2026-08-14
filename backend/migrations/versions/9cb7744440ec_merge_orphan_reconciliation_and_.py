"""merge orphan reconciliation and quarantine retention heads

Revision ID: 9cb7744440ec
Revises: a7c39f2e5d81, c48e6a1f9d73
Create Date: 2026-08-14 21:46:23.104422

"""
from typing import Sequence, Union


revision: str = '9cb7744440ec'
down_revision: Union[str, None] = ('a7c39f2e5d81', 'c48e6a1f9d73')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
