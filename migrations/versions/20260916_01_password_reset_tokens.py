"""Store password reset tokens as hashes.

Revision ID: 20260916_01
Revises: 20260915_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260916_01"
down_revision = "20260915_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("utilisateur_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["utilisateur_id"], ["utilisateurs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_password_reset_tokens_utilisateur", "password_reset_tokens", ["utilisateur_id"])


def downgrade():
    op.drop_index("ix_password_reset_tokens_utilisateur", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")