"""Initial portable ClasseXP schema.

Revision ID: 20260913_01
Revises:
"""

from alembic import op

from models import metadata


revision = "20260913_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    metadata.drop_all(bind=op.get_bind(), checkfirst=True)
