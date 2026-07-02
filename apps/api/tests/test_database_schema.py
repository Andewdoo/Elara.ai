import importlib.util
import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, ForeignKeyConstraint, Numeric, Uuid
from sqlalchemy.dialects.postgresql import CITEXT, dialect as postgresql_dialect

from app.database.base import Base
from app.database.constants import PASSAGE_EMBEDDING_DIMENSION
from app.models import (
    AccessStatus,
    Calculation,
    DependencyRelationship,
    EvidenceStance,
    InputType,
    ResearchDepth,
    RunStatus,
    SourcePassage,
    SourceSnapshot,
    SourceType,
    User,
)


API_ROOT = Path(__file__).resolve().parents[1]
REVISION_PATH = API_ROOT / "migrations" / "versions" / "20260626_0001_research_schema.py"


def _load_revision():
    spec = importlib.util.spec_from_file_location("initial_research_schema", REVISION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_durable_tables_are_registered_in_metadata():
    expected = {
        "users",
        "verification_runs",
        "atomic_claims",
        "search_queries",
        "sources",
        "source_snapshots",
        "run_sources",
        "source_passages",
        "evidence_items",
        "information_clusters",
        "source_dependencies",
        "calculations",
        "agent_events",
        "report_citations",
        "user_feedback",
        "methodology_versions",
        "exports",
    }
    assert set(Base.metadata.tables) == expected


def test_models_use_configured_vector_and_decimal_audit_types():
    embedding_type = SourcePassage.__table__.c.embedding.type
    assert isinstance(embedding_type, Vector)
    assert embedding_type.dim == PASSAGE_EMBEDDING_DIMENSION
    assert isinstance(Calculation.__table__.c.inputs.type, JSON)
    assert isinstance(Calculation.__table__.c.result.type, JSON)
    assert isinstance(Calculation.__table__.c.decimal_context.type, JSON)
    assert isinstance(SourceSnapshot.__table__.c.extraction_quality.type, Numeric)
    assert {"inputs", "result", "decimal_context", "audit_status"} <= set(
        Calculation.__table__.c.keys()
    )
    assert isinstance(
        User.__table__.c.email.type.dialect_impl(postgresql_dialect()), CITEXT
    )


def test_initial_migration_enables_required_postgresql_extensions():
    source = REVISION_PATH.read_text(encoding="utf-8")
    assert 'op.execute("CREATE EXTENSION IF NOT EXISTS vector")' in source
    assert 'op.execute("CREATE EXTENSION IF NOT EXISTS citext")' in source


def test_enum_contracts_match_the_initial_migration():
    revision = _load_revision()
    enum_classes = {
        "run_status": RunStatus,
        "input_type": InputType,
        "research_depth": ResearchDepth,
        "source_type": SourceType,
        "access_status": AccessStatus,
        "evidence_stance": EvidenceStance,
        "dependency_relationship": DependencyRelationship,
    }
    assert {
        name: tuple(member.value for member in enum_class)
        for name, enum_class in enum_classes.items()
    } == revision.ENUMS


def test_initial_migration_tables_match_metadata_and_has_one_head():
    revision = _load_revision()
    migrated_tables = {
        match.group(1)
        for statement in revision.TABLE_SQL
        if (match := re.match(r"CREATE TABLE (\w+)", statement))
    }
    assert migrated_tables == set(Base.metadata.tables)
    assert revision.down_revision is None
    assert any("vector(__EMBEDDING_DIMENSION__)" in sql for sql in revision.TABLE_SQL)
    assert any("ix_source_snapshots_source_content_hash" in sql for sql in revision.INDEX_SQL)
    assert any("trg_source_snapshots_immutable" in sql for sql in revision.POST_TABLE_SQL)
    assert any("trg_methodology_versions_immutable" in sql for sql in revision.POST_TABLE_SQL)
    snapshot_constraints = {
        constraint.name for constraint in SourceSnapshot.__table__.constraints
    }
    assert "uq_source_snapshots_source_version" in snapshot_constraints

    config = Config(str(API_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20260702_0002"]


def test_uuid_keys_and_timezone_aware_timestamps_are_consistent():
    for table in Base.metadata.tables.values():
        assert table.primary_key.columns
        assert all(isinstance(column.type, Uuid) for column in table.primary_key.columns)
        for column in table.columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone, f"{table.name}.{column.name} must use timestamptz"


def test_snapshot_provenance_and_methodology_links_are_protected():
    run_sources = Base.metadata.tables["run_sources"]
    passages = Base.metadata.tables["source_passages"]
    composite_foreign_keys = {
        constraint.name
        for table in (run_sources, passages)
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint) and len(constraint.columns) == 2
    }
    assert composite_foreign_keys == {
        "fk_run_sources_snapshot_source",
        "fk_source_passages_snapshot_source",
    }

    methodology_fk = next(
        iter(Base.metadata.tables["verification_runs"].c.methodology_version_id.foreign_keys)
    )
    assert methodology_fk.ondelete == "RESTRICT"


def test_ownership_status_and_graph_indexes_are_explicit():
    expected_indexes = {
        "ix_verification_runs_owner_created",
        "ix_verification_runs_status_queued",
        "ix_source_dependencies_run_relationship",
        "ix_source_dependencies_parent",
        "ix_source_dependencies_child",
        "ix_user_feedback_user_created",
    }
    metadata_indexes = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
    }
    assert expected_indexes <= metadata_indexes


def test_step15_constraints_and_columns_are_registered():
    runs = Base.metadata.tables["verification_runs"]
    assert {"saved_at", "deleted_at"} <= set(runs.c.keys())
    constraint_names = {
        constraint.name
        for table_name in ("user_feedback", "exports")
        for constraint in Base.metadata.tables[table_name].constraints
    }
    assert {"ck_user_feedback_category", "ck_exports_type"} <= constraint_names
