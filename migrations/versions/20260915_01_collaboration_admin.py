"""Collaborative classes, corrections, chat and site administration.

Revision ID: 20260915_01
Revises: 20260913_01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from models import (
    audit_logs, class_settings, classe_professeurs, conversation_participants,
    conversations, messages, notifications, site_banners, site_content, site_settings,
)

revision = "20260915_01"
down_revision = "20260913_01"
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {column["name"] for column in inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    user_constraint = next((c for c in inspector.get_check_constraints("utilisateurs") if "role" in (c.get("name") or "")), None)
    if user_constraint and "ADMIN" not in (user_constraint.get("sqltext") or ""):
        with op.batch_alter_table("utilisateurs") as batch:
            batch.drop_constraint(op.f(user_constraint["name"]), type_="check")
            batch.create_check_constraint("role_valide", "role IN ('ELEVE', 'PROFESSEUR', 'ADMIN')")

    member_columns = _columns(bind, "classe_eleves")
    additions = {
        "role": sa.Column("role", sa.String(20), nullable=False, server_default="ELEVE"),
        "statut": sa.Column("statut", sa.String(20), nullable=False, server_default="ACTIVE"),
        "removed_at": sa.Column("removed_at", sa.DateTime()),
        "removed_by": sa.Column("removed_by", sa.Integer()),
        "can_view_members": sa.Column("can_view_members", sa.Boolean(), nullable=False, server_default=sa.true()),
        "can_send_announcements": sa.Column("can_send_announcements", sa.Boolean(), nullable=False, server_default=sa.false()),
        "can_contact_students": sa.Column("can_contact_students", sa.Boolean(), nullable=False, server_default=sa.false()),
        "can_contact_teachers": sa.Column("can_contact_teachers", sa.Boolean(), nullable=False, server_default=sa.true()),
    }
    with op.batch_alter_table("classe_eleves") as batch:
        for name, column in additions.items():
            if name not in member_columns:
                batch.add_column(column)

    assignment_columns = _columns(bind, "devoirs")
    with op.batch_alter_table("devoirs") as batch:
        if "correction_text" not in assignment_columns:
            batch.add_column(sa.Column("correction_text", sa.Text()))
        if "correction_visibility" not in assignment_columns:
            batch.add_column(sa.Column("correction_visibility", sa.String(30), nullable=False, server_default="NEVER"))
        if "correction_visible_at" not in assignment_columns:
            batch.add_column(sa.Column("correction_visible_at", sa.DateTime()))

    for table in (classe_professeurs, class_settings, conversations, conversation_participants,
                  messages, notifications, site_content, site_banners, site_settings, audit_logs):
        if table.name not in tables:
            table.create(bind=bind, checkfirst=True)

    file_constraint = next((c for c in inspect(bind).get_check_constraints("fichiers") if "kind" in (c.get("name") or "")), None)
    if file_constraint and "SITE_IMAGE" not in (file_constraint.get("sqltext") or ""):
        with op.batch_alter_table("fichiers") as batch:
            batch.drop_constraint(op.f(file_constraint["name"]), type_="check")
            batch.create_check_constraint("kind_valide", "kind IN ('SUJET','COPIE','CORRECTION','PHOTO','SITE_IMAGE')")

    # Preserve the legacy owner relation; reruns remain idempotent.
    bind.execute(sa.text(
        "INSERT INTO classe_professeurs (classe_id, professeur_id, role, ajoute_par) "
        "SELECT id, professeur_id, 'OWNER', professeur_id FROM classes "
        "WHERE professeur_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM classe_professeurs cp WHERE cp.classe_id=classes.id)"
    ))
    bind.execute(sa.text(
        "INSERT INTO class_settings (classe_id) SELECT id FROM classes WHERE NOT EXISTS ("
        "SELECT 1 FROM class_settings cs WHERE cs.classe_id=classes.id)"
    ))
    bind.execute(sa.text(
        "INSERT INTO site_settings (id, public_name, primary_color) "
        "SELECT 1, 'ClasseXP', 'indigo' WHERE NOT EXISTS (SELECT 1 FROM site_settings WHERE id=1)"
    ))


def downgrade():
    bind = op.get_bind()
    for table in (audit_logs, site_banners, site_content, site_settings, notifications,
                  messages, conversation_participants, conversations, class_settings, classe_professeurs):
        table.drop(bind=bind, checkfirst=True)
    file_constraint = next((c for c in inspect(bind).get_check_constraints("fichiers") if "kind" in (c.get("name") or "")), None)
    if file_constraint and "SITE_IMAGE" in (file_constraint.get("sqltext") or ""):
        with op.batch_alter_table("fichiers") as batch:
            batch.drop_constraint(op.f(file_constraint["name"]), type_="check")
            batch.create_check_constraint("kind_valide", "kind IN ('SUJET','COPIE','CORRECTION','PHOTO')")
    assignment_checks = inspect(bind).get_check_constraints("devoirs")
    visibility_check = next((c for c in assignment_checks if "correction_visibility" in (c.get("sqltext") or "")), None)
    with op.batch_alter_table("devoirs") as batch:
        if visibility_check:
            batch.drop_constraint(op.f(visibility_check["name"]), type_="check")
        for name in ("correction_visible_at", "correction_visibility", "correction_text"):
            if name in _columns(bind, "devoirs"):
                batch.drop_column(name)
    member_checks = inspect(bind).get_check_constraints("classe_eleves")
    with op.batch_alter_table("classe_eleves") as batch:
        for constraint in member_checks:
            if any(column in (constraint.get("sqltext") or "") for column in ("statut", "role")):
                batch.drop_constraint(op.f(constraint["name"]), type_="check")
        for name in ("can_contact_teachers", "can_contact_students", "can_send_announcements",
                     "can_view_members", "removed_by", "removed_at", "statut", "role"):
            if name in _columns(bind, "classe_eleves"):
                batch.drop_column(name)
    user_constraint = next((c for c in inspect(bind).get_check_constraints("utilisateurs") if "role" in (c.get("name") or "")), None)
    if user_constraint and "ADMIN" in (user_constraint.get("sqltext") or ""):
        with op.batch_alter_table("utilisateurs") as batch:
            batch.drop_constraint(op.f(user_constraint["name"]), type_="check")
            batch.create_check_constraint("role_valide", "role IN ('ELEVE', 'PROFESSEUR')")
