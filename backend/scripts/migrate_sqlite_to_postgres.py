"""One-shot SQLite → Postgres data migration.

Walks every SQLAlchemy model in dependency order, copies all rows from a source
SQLite file into a target Postgres database (preserving primary-key ids), and
fixes the Postgres sequences so future inserts don't collide with imported ids.

The whole copy runs inside a single Postgres transaction, so a partial failure
leaves the target database untouched.

Usage:
    .venv/bin/python -m scripts.migrate_sqlite_to_postgres \\
        --source ./audithealth.db \\
        --target postgresql+psycopg://audithealth:audithealth@localhost:5432/audithealth

Defaults: --source ./audithealth.db, --target $DATABASE_URL.
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.models import (
    Audit,
    AuditSection,
    Business,
    Competitor,
    CompetitorObservation,
    Recommendation,
    Session as SessionModel,
    Subscription,
    User,
)

# Parents before children. CompetitorObservation last because it depends on
# both Competitor and Audit.
MIGRATION_ORDER = [
    User,
    Business,
    Subscription,
    SessionModel,
    Audit,
    Competitor,
    AuditSection,
    Recommendation,
    CompetitorObservation,
]


def _resolve_target_url(target_arg: str | None) -> str:
    if target_arg:
        return target_arg
    env = os.environ.get("DATABASE_URL")
    if not env:
        sys.exit(
            "error: --target not given and DATABASE_URL is not set.\n"
            "       Pass --target postgresql+psycopg://user:pw@host:5432/db"
        )
    return env


def _copy_table(model, src_session, dst_conn) -> int:
    table = model.__table__
    rows = src_session.execute(select(model)).scalars().all()
    if not rows:
        return 0
    payload = [
        {col.name: getattr(row, col.name) for col in table.columns}
        for row in rows
    ]
    dst_conn.execute(table.insert(), payload)
    return len(payload)


def _reset_sequence(model, dst_conn) -> None:
    table = model.__table__
    pk_cols = list(table.primary_key.columns)
    if len(pk_cols) != 1:
        return
    pk = pk_cols[0]
    try:
        is_int_pk = pk.type.python_type is int
    except NotImplementedError:
        return
    if not is_int_pk:
        return
    # setval(seq, NULL) errors out, so skip empty tables.
    max_id = dst_conn.execute(select(func.max(pk))).scalar()
    if max_id is None:
        return
    dst_conn.execute(
        text(
            "SELECT setval("
            f"pg_get_serial_sequence('{table.name}', '{pk.name}'), "
            f"(SELECT MAX({pk.name}) FROM {table.name})"
            ")"
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy AuditHealth data from a SQLite file into a Postgres database.",
    )
    parser.add_argument(
        "--source",
        default="./audithealth.db",
        help="Path to the source SQLite file (default: ./audithealth.db).",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Target Postgres URL (default: $DATABASE_URL).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Migrate even if the target Postgres has existing users.",
    )
    args = parser.parse_args()

    if not os.path.exists(args.source):
        sys.exit(f"error: source SQLite file not found: {args.source}")

    source_url = f"sqlite:///{args.source}"
    target_url = _resolve_target_url(args.target)

    if not target_url.startswith("postgresql"):
        sys.exit(
            f"error: --target must be a Postgres URL, got: {target_url}\n"
            "       Use postgresql+psycopg://user:pw@host:5432/db"
        )

    src_engine = create_engine(source_url, future=True)
    dst_engine = create_engine(target_url, future=True)

    with dst_engine.connect() as conn:
        existing_users = conn.execute(
            select(func.count()).select_from(User.__table__)
        ).scalar_one()
    if existing_users > 0 and not args.force:
        sys.exit(
            f"error: target Postgres already has {existing_users} user(s). "
            "Refusing to import (re-run with --force to override)."
        )

    SrcSession = sessionmaker(
        bind=src_engine, autoflush=False, autocommit=False, future=True
    )
    src_session = SrcSession()

    counts: dict[str, int] = {}
    try:
        # Single Postgres transaction — partial failure rolls back cleanly.
        with dst_engine.begin() as dst_conn:
            for model in MIGRATION_ORDER:
                counts[model.__table__.name] = _copy_table(model, src_session, dst_conn)
            for model in MIGRATION_ORDER:
                _reset_sequence(model, dst_conn)
    finally:
        src_session.close()

    print("\nMigration complete. Rows copied (in dependency order):")
    for model in MIGRATION_ORDER:
        name = model.__table__.name
        print(f"  {name:<26} {counts.get(name, 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
