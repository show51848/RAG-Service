"""initial schema

Revision ID: 45606695ceea
Revises:
Create Date: 2026-08-08 00:57:31.447212

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '45606695ceea'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Matches app.models.document.DocumentStatus. Kept in sync manually since this
# migration predates any autogenerate run against a live database.
document_status_enum = sa.Enum(
    "pending", "processing", "indexed", "failed", name="documentstatus"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("original_name", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("status", document_status_enum, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("file_hash", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_documents_content_hash"), "documents", ["content_hash"], unique=False
    )
    op.create_index(
        op.f("ix_documents_file_hash"), "documents", ["file_hash"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_documents_file_hash"), table_name="documents")
    op.drop_index(op.f("ix_documents_content_hash"), table_name="documents")
    op.drop_table("documents")
    op.drop_table("users")

    # op.drop_table() does not drop the native Postgres ENUM type it depended
    # on — without this, re-running upgrade() after a downgrade fails with
    # "type documentstatus already exists".
    document_status_enum.drop(op.get_bind(), checkfirst=True)
