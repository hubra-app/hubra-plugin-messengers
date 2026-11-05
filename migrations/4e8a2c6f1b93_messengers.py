"""messengers log

Runs in public and in every club's schema, tracked in its own version table
(alembic_version_messengers). has_table() keeps it safe to run twice.

Revision ID: 4e8a2c6f1b93
Revises:
Create Date: 2026-11-05 15:00:00

"""

from alembic import op
import sqlalchemy as sa

from hubra.core.plugins.ops import has_table

revision = "4e8a2c6f1b93"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    if not has_table("messengers_log"):
        op.create_table(
            "messengers_log",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("channel", sa.String(10), nullable=False),
            sa.Column("kind", sa.String(12), nullable=False),
            sa.Column("ref", sa.String(40), nullable=True),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("status", sa.String(8), nullable=False),
            sa.Column("error", sa.String(300), nullable=True),
            sa.Column("tries", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_messengers_log_status", "messengers_log", ["status"])


def downgrade():
    if has_table("messengers_log"):
        op.drop_table("messengers_log")
