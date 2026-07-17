"""initial production schema

Revision ID: 20260717_01
Revises: 
Create Date: 2026-07-17 12:25:06.355725
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

from app.extensions import db
import app.models  # noqa: F401 - register all tables for legacy adoption

revision: str = '20260717_01'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_TABLES = {
    'users',
    'model_profiles',
    'datasets',
    'dataset_tasks',
    'dataset_images',
    'dataset_exports',
    'training_workers',
    'training_jobs',
    'training_artifacts',
    'training_inference_jobs',
}

LEGACY_UUID_COLUMNS = {
    'users': ('id',),
    'model_profiles': ('id', 'user_id'),
    'datasets': ('id', 'user_id'),
    'dataset_tasks': ('id', 'dataset_id', 'user_id'),
    'dataset_images': ('id', 'dataset_id', 'source_task_id'),
    'dataset_exports': ('id', 'dataset_id'),
    'training_jobs': ('id', 'dataset_id', 'user_id', 'export_id'),
    'training_artifacts': ('id', 'job_id'),
    'training_inference_jobs': ('id', 'training_job_id', 'dataset_id', 'user_id', 'artifact_id'),
}

LEGACY_JSON_COLUMNS = {
    'datasets': ('categories', 'annotation_json'),
    'dataset_tasks': ('categories', 'config_json', 'prompt_json'),
    'dataset_images': ('diversity_vars', 'detection_categories'),
    'dataset_exports': ('summary_json',),
    'training_workers': ('capabilities_json',),
    'training_jobs': ('config_json', 'metrics_json'),
    'training_inference_jobs': ('detections_json',),
}


def _legacy_table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column['name'] for column in sa.inspect(bind).get_columns(table_name)}


def _drop_legacy_foreign_keys(bind, table_names: set[str]) -> None:
    if bind.dialect.name != 'postgresql':
        return
    inspector = sa.inspect(bind)
    for table_name in sorted(table_names & LEGACY_TABLES):
        for foreign_key in inspector.get_foreign_keys(table_name):
            if foreign_key.get('name'):
                op.drop_constraint(foreign_key['name'], table_name, type_='foreignkey')


def _convert_legacy_postgresql_types(bind, table_names: set[str]) -> None:
    if bind.dialect.name != 'postgresql':
        return
    preparer = bind.dialect.identifier_preparer
    for table_name, column_names in LEGACY_UUID_COLUMNS.items():
        if table_name not in table_names:
            continue
        available = _column_names(bind, table_name)
        quoted_table = preparer.quote(table_name)
        for column_name in column_names:
            if column_name not in available:
                continue
            quoted_column = preparer.quote(column_name)
            column = next(
                column
                for column in sa.inspect(bind).get_columns(table_name)
                if column['name'] == column_name
            )
            if isinstance(column['type'], sa.Uuid):
                continue
            nullable = column['nullable']
            using = f'NULLIF({quoted_column}, \'\')::uuid' if nullable else f'{quoted_column}::uuid'
            op.execute(
                sa.text(
                    f'ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} '
                    f'TYPE UUID USING {using}'
                )
            )

    for table_name, column_names in LEGACY_JSON_COLUMNS.items():
        if table_name not in table_names:
            continue
        available = _column_names(bind, table_name)
        quoted_table = preparer.quote(table_name)
        for column_name in column_names:
            if column_name not in available:
                continue
            column = next(
                column
                for column in sa.inspect(bind).get_columns(table_name)
                if column['name'] == column_name
            )
            if isinstance(column['type'], postgresql.JSONB):
                continue
            quoted_column = preparer.quote(column_name)
            op.execute(
                sa.text(
                    f'ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} '
                    f'TYPE JSONB USING {quoted_column}::jsonb'
                )
            )

    numeric_columns = {
        'datasets': ('spent_cost',),
        'dataset_tasks': ('estimated_cost', 'spent_cost'),
    }
    for table_name, column_names in numeric_columns.items():
        if table_name not in table_names:
            continue
        available = _column_names(bind, table_name)
        quoted_table = preparer.quote(table_name)
        for column_name in column_names:
            if column_name in available:
                quoted_column = preparer.quote(column_name)
                op.execute(
                    sa.text(
                        f'ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} '
                        f'TYPE NUMERIC(14, 4) USING {quoted_column}::numeric(14, 4)'
                    )
                )


def _json_server_default(bind, value: str) -> sa.TextClause:
    suffix = '::jsonb' if bind.dialect.name == 'postgresql' else ''
    return sa.text(f"'{value}'{suffix}")


def _add_legacy_columns(bind, table_names: set[str]) -> None:
    uuid_type = sa.Uuid(as_uuid=False)
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql')
    column_specs: dict[str, tuple[sa.Column, ...]] = {
        'model_profiles': (
            sa.Column('key_version', sa.Integer(), nullable=False, server_default='1'),
        ),
        'datasets': (
            sa.Column('next_image_ordinal', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('next_export_version', sa.Integer(), nullable=False, server_default='1'),
        ),
        'dataset_tasks': (
            sa.Column('source_asset_id', uuid_type, nullable=True),
        ),
        'dataset_images': (
            sa.Column('asset_id', uuid_type, nullable=True),
            sa.Column('detection_categories', json_type, nullable=False, server_default=_json_server_default(bind, '[]')),
        ),
        'dataset_exports': (
            sa.Column('asset_id', uuid_type, nullable=True),
            sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        ),
        'training_workers': (
            sa.Column('token_hash', sa.String(length=128), nullable=False, server_default=''),
            sa.Column(
                'token_scopes',
                json_type,
                nullable=False,
                server_default=_json_server_default(bind, '["training", "inference"]'),
            ),
        ),
        'training_jobs': (
            sa.Column('assignment_token_hash', sa.String(length=128), nullable=False, server_default=''),
            sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        ),
        'training_artifacts': (
            sa.Column('asset_id', uuid_type, nullable=True),
        ),
        'training_inference_jobs': (
            sa.Column('input_asset_id', uuid_type, nullable=True),
            sa.Column('result_asset_id', uuid_type, nullable=True),
            sa.Column('assignment_token_hash', sa.String(length=128), nullable=False, server_default=''),
            sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        ),
    }
    for table_name, columns in column_specs.items():
        if table_name not in table_names:
            continue
        existing_columns = _column_names(bind, table_name)
        for column in columns:
            if column.name not in existing_columns:
                op.add_column(table_name, column)


def _drop_temporary_legacy_defaults(bind, table_names: set[str]) -> None:
    if bind.dialect.name != 'postgresql':
        return
    temporary_defaults = {
        'dataset_images': ('detection_categories',),
        'training_workers': ('token_hash', 'token_scopes'),
        'training_jobs': ('assignment_token_hash',),
        'training_inference_jobs': ('assignment_token_hash',),
    }
    for table_name, column_names in temporary_defaults.items():
        if table_name not in table_names:
            continue
        available = _column_names(bind, table_name)
        for column_name in column_names:
            if column_name in available:
                op.alter_column(table_name, column_name, server_default=None)


def _backfill_legacy_counters_and_categories(bind, table_names: set[str]) -> None:
    if 'datasets' not in table_names:
        return
    if 'dataset_images' in table_names:
        op.execute(
            sa.text(
                'UPDATE datasets SET next_image_ordinal = COALESCE('
                '(SELECT MAX(dataset_images.ordinal) + 1 FROM dataset_images '
                'WHERE dataset_images.dataset_id = datasets.id), 1)'
            )
        )
    if 'dataset_exports' in table_names:
        op.execute(
            sa.text(
                'UPDATE datasets SET next_export_version = COALESCE('
                '(SELECT MAX(dataset_exports.version) + 1 FROM dataset_exports '
                'WHERE dataset_exports.dataset_id = datasets.id), 1)'
            )
        )

    category_table = db.metadata.tables['dataset_categories']
    existing_dataset_ids = set(
        bind.execute(sa.select(category_table.c.dataset_id).distinct()).scalars()
    )
    datasets = db.metadata.tables['datasets']
    rows = bind.execute(sa.select(datasets.c.id, datasets.c.categories)).all()
    inserts: list[dict[str, object]] = []
    for dataset_id, categories in rows:
        if dataset_id in existing_dataset_ids:
            continue
        seen: set[str] = set()
        for position, value in enumerate(categories or []):
            name = str(value).strip()
            if not name or name in seen:
                continue
            inserts.append(
                {
                    'id': str(uuid.uuid4()),
                    'dataset_id': dataset_id,
                    'name': name,
                    'position': len(seen),
                    'active': True,
                }
            )
            seen.add(name)
    if inserts:
        bind.execute(category_table.insert(), inserts)


def _recreate_legacy_foreign_keys(bind, legacy_tables: set[str]) -> None:
    if bind.dialect.name != 'postgresql':
        return
    for table_name in sorted(legacy_tables & LEGACY_TABLES):
        table = db.metadata.tables[table_name]
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            referred_table = elements[0].column.table.name
            if referred_table not in _legacy_table_names(bind):
                continue
            local_columns = [element.parent.name for element in elements]
            remote_columns = [element.column.name for element in elements]
            constraint_name = f"fk_{table_name}_{'_'.join(local_columns)}_{referred_table}"
            op.create_foreign_key(
                constraint_name,
                table_name,
                referred_table,
                local_columns,
                remote_columns,
                ondelete=elements[0].ondelete,
            )


def _create_missing_legacy_indexes(bind, legacy_tables: set[str]) -> None:
    for table_name in sorted(legacy_tables & LEGACY_TABLES):
        existing_names = {
            index['name'] for index in sa.inspect(bind).get_indexes(table_name) if index.get('name')
        }
        for index in db.metadata.tables[table_name].indexes:
            if not index.name or index.name in existing_names:
                continue
            column_names = [expression.name for expression in index.expressions if hasattr(expression, 'name')]
            if len(column_names) == len(index.expressions):
                op.create_index(index.name, table_name, column_names, unique=index.unique)


def _upgrade_legacy_schema(bind, legacy_tables: set[str]) -> None:
    """Adopt a schema created by the pre-Alembic AUTO_CREATE_SCHEMA release."""
    _drop_legacy_foreign_keys(bind, legacy_tables)
    _convert_legacy_postgresql_types(bind, legacy_tables)
    _add_legacy_columns(bind, legacy_tables)
    _drop_temporary_legacy_defaults(bind, legacy_tables)
    db.metadata.create_all(bind=bind, checkfirst=True)
    current_tables = _legacy_table_names(bind)
    _backfill_legacy_counters_and_categories(bind, current_tables)
    _recreate_legacy_foreign_keys(bind, legacy_tables)
    _create_missing_legacy_indexes(bind, legacy_tables)


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = _legacy_table_names(bind)
    if 'users' in existing_tables:
        _upgrade_legacy_schema(bind, existing_tables)
        return
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('outbox_events',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('aggregate_type', sa.String(length=64), nullable=False),
    sa.Column('aggregate_id', sa.String(length=64), nullable=False),
    sa.Column('deduplication_key', sa.String(length=255), nullable=False),
    sa.Column('payload_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('attempt_count >= 0', name='ck_outbox_events_attempts_nonnegative'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('deduplication_key', name='uq_outbox_events_deduplication_key')
    )
    with op.batch_alter_table('outbox_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_outbox_events_aggregate_id'), ['aggregate_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_outbox_events_event_type'), ['event_type'], unique=False)
        batch_op.create_index('ix_outbox_events_pending', ['published_at', 'available_at', 'created_at'], unique=False)

    op.create_table('training_workers',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('capabilities_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('current_job_id', sa.String(length=36), nullable=True),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('token_scopes', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('training_workers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_training_workers_current_job_id'), ['current_job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_workers_status'), ['status'], unique=False)

    op.create_table('users',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('plan', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('datasets',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('categories', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('image_count', sa.Integer(), nullable=False),
    sa.Column('selected_count', sa.Integer(), nullable=False),
    sa.Column('task_count', sa.Integer(), nullable=False),
    sa.Column('next_image_ordinal', sa.Integer(), server_default='1', nullable=False),
    sa.Column('next_export_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('spent_cost', sa.Numeric(precision=14, scale=4), server_default='0', nullable=False),
    sa.Column('annotation_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('image_count >= 0', name='ck_datasets_image_count_nonnegative'),
    sa.CheckConstraint('selected_count >= 0', name='ck_datasets_selected_count_nonnegative'),
    sa.CheckConstraint('spent_cost >= 0', name='ck_datasets_spent_cost_nonnegative'),
    sa.CheckConstraint('task_count >= 0', name='ck_datasets_task_count_nonnegative'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_datasets_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_datasets_user_id'), ['user_id'], unique=False)

    op.create_table('idempotency_records',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('scope', sa.String(length=255), nullable=False),
    sa.Column('idempotency_key', sa.String(length=255), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('response_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'scope', 'idempotency_key', name='uq_idempotency_user_scope_key')
    )
    with op.batch_alter_table('idempotency_records', schema=None) as batch_op:
        batch_op.create_index('ix_idempotency_records_expiry', ['expires_at', 'completed_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_idempotency_records_user_id'), ['user_id'], unique=False)

    op.create_table('model_profiles',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('profile_type', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('base_url', sa.String(length=255), nullable=True),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('api_key_encrypted', sa.Text(), nullable=False),
    sa.Column('key_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('concurrency', sa.Integer(), nullable=False),
    sa.Column('batch_size', sa.Integer(), nullable=False),
    sa.Column('jimeng_watermark', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('model_profiles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_model_profiles_user_id'), ['user_id'], unique=False)

    op.create_table('refresh_sessions',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('family_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revocation_reason', sa.String(length=32), nullable=False),
    sa.Column('rotated_to_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('successor_token_encrypted', sa.Text(), nullable=False),
    sa.Column('rotation_grace_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('user_agent', sa.String(length=512), nullable=False),
    sa.Column('ip_address', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['rotated_to_id'], ['refresh_sessions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash', name='uq_refresh_sessions_token_hash')
    )
    with op.batch_alter_table('refresh_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_refresh_sessions_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_refresh_sessions_family_id'), ['family_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_refresh_sessions_rotated_to_id'), ['rotated_to_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_refresh_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('assets',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('dataset_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('storage_backend', sa.String(length=32), server_default='local', nullable=False),
    sa.Column('storage_key', sa.String(length=1024), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=128), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('metadata_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('size_bytes >= 0', name='ck_assets_size_nonnegative'),
    sa.CheckConstraint('width >= 0 AND height >= 0', name='ck_assets_dimensions_nonnegative'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('storage_backend', 'storage_key', name='uq_assets_backend_key')
    )
    with op.batch_alter_table('assets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_assets_dataset_id'), ['dataset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_assets_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_assets_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_assets_sha256'), ['sha256'], unique=False)
        batch_op.create_index(batch_op.f('ix_assets_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_assets_user_id'), ['user_id'], unique=False)

    op.create_table('dataset_categories',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('dataset_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('position >= 0', name='ck_dataset_categories_position_nonnegative'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dataset_id', 'name', name='uq_dataset_categories_dataset_name'),
    sa.UniqueConstraint('dataset_id', 'position', name='uq_dataset_categories_dataset_position')
    )
    with op.batch_alter_table('dataset_categories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dataset_categories_dataset_id'), ['dataset_id'], unique=False)

    op.create_table('dataset_exports',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('dataset_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('asset_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('export_format', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('summary_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('download_url', sa.String(length=255), nullable=False),
    sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('attempt_count >= 0', name='ck_dataset_exports_attempts_nonnegative'),
    sa.CheckConstraint('version > 0', name='ck_dataset_exports_version_positive'),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dataset_id', 'version', name='uq_dataset_exports_dataset_version')
    )
    with op.batch_alter_table('dataset_exports', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dataset_exports_asset_id'), ['asset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_exports_dataset_id'), ['dataset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_exports_lease_expires_at'), ['lease_expires_at'], unique=False)

    op.create_table('dataset_tasks',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('dataset_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('task_type', sa.String(length=32), nullable=False),
    sa.Column('task_name', sa.String(length=255), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('image_count', sa.Integer(), nullable=False),
    sa.Column('categories', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('config_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('prompt_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('progress_percent', sa.Integer(), nullable=False),
    sa.Column('images_generated', sa.Integer(), nullable=False),
    sa.Column('selected_count', sa.Integer(), nullable=False),
    sa.Column('estimated_cost', sa.Numeric(precision=14, scale=4), server_default='0', nullable=False),
    sa.Column('spent_cost', sa.Numeric(precision=14, scale=4), server_default='0', nullable=False),
    sa.Column('api_provider', sa.String(length=64), nullable=False),
    sa.Column('api_key_encrypted', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_asset_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('image_count >= 0', name='ck_dataset_tasks_image_count_nonnegative'),
    sa.CheckConstraint('progress_percent >= 0 AND progress_percent <= 100', name='ck_dataset_tasks_progress_range'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_asset_id'], ['assets.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('dataset_tasks', schema=None) as batch_op:
        batch_op.create_index('ix_dataset_tasks_dataset_created_at', ['dataset_id', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_tasks_dataset_id'), ['dataset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_tasks_source_asset_id'), ['source_asset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_tasks_status'), ['status'], unique=False)
        batch_op.create_index('ix_dataset_tasks_status_created_at', ['status', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_tasks_task_type'), ['task_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_tasks_user_id'), ['user_id'], unique=False)

    op.create_table('dataset_images',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('dataset_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('source_task_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('asset_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('source_type', sa.String(length=32), nullable=False),
    sa.Column('source_ordinal', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('seed', sa.Integer(), nullable=False),
    sa.Column('prompt_text', sa.Text(), nullable=False),
    sa.Column('diversity_vars', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('preview_svg', sa.Text(), nullable=False),
    sa.Column('selected', sa.Boolean(), nullable=False),
    sa.Column('annotation_status', sa.String(length=32), nullable=False),
    sa.Column('confidence_score', sa.Float(), nullable=True),
    sa.Column('detection_categories', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)', name='ck_dataset_images_confidence_range'),
    sa.CheckConstraint('ordinal > 0', name='ck_dataset_images_ordinal_positive'),
    sa.CheckConstraint('source_ordinal > 0', name='ck_dataset_images_source_ordinal_positive'),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_task_id'], ['dataset_tasks.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dataset_id', 'ordinal', name='uq_dataset_images_dataset_ordinal'),
    sa.UniqueConstraint('source_task_id', 'source_ordinal', name='uq_dataset_images_task_ordinal')
    )
    with op.batch_alter_table('dataset_images', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dataset_images_asset_id'), ['asset_id'], unique=False)
        batch_op.create_index('ix_dataset_images_dataset_annotation_status', ['dataset_id', 'annotation_status'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_images_dataset_id'), ['dataset_id'], unique=False)
        batch_op.create_index('ix_dataset_images_dataset_selected_ordinal', ['dataset_id', 'selected', 'ordinal'], unique=False)
        batch_op.create_index(batch_op.f('ix_dataset_images_source_task_id'), ['source_task_id'], unique=False)

    op.create_table('task_items',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('task_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('item_index', sa.Integer(), nullable=False),
    sa.Column('item_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('payload_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('result_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lease_token_hash', sa.String(length=128), nullable=False),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('attempt_count >= 0', name='ck_task_items_attempts_nonnegative'),
    sa.CheckConstraint('item_index > 0', name='ck_task_items_index_positive'),
    sa.ForeignKeyConstraint(['task_id'], ['dataset_tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'item_index', name='uq_task_items_task_index')
    )
    with op.batch_alter_table('task_items', schema=None) as batch_op:
        batch_op.create_index('ix_task_items_dispatch', ['status', 'available_at', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_task_items_lease_expires_at'), ['lease_expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_task_items_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_task_items_task_id'), ['task_id'], unique=False)

    op.create_table('training_jobs',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('dataset_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('export_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('worker_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('progress_percent', sa.Integer(), nullable=False),
    sa.Column('config_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('metrics_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('assignment_token_hash', sa.String(length=128), nullable=False),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('progress_percent >= 0 AND progress_percent <= 100', name='ck_training_jobs_progress_range'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['export_id'], ['dataset_exports.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['worker_id'], ['training_workers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('training_jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_training_jobs_dataset_id'), ['dataset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_jobs_export_id'), ['export_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_jobs_lease_expires_at'), ['lease_expires_at'], unique=False)
        batch_op.create_index('ix_training_jobs_queue', ['status', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_jobs_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_jobs_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_jobs_worker_id'), ['worker_id'], unique=False)

    op.create_table('annotation_revisions',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('image_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('bbox_semantics', sa.String(length=32), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('metadata_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('revision > 0', name='ck_annotation_revisions_revision_positive'),
    sa.ForeignKeyConstraint(['image_id'], ['dataset_images.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('image_id', 'revision', name='uq_annotation_revisions_image_revision')
    )
    with op.batch_alter_table('annotation_revisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_annotation_revisions_image_id'), ['image_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_annotation_revisions_is_current'), ['is_current'], unique=False)

    op.create_table('training_artifacts',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('job_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('asset_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('artifact_type', sa.String(length=32), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('storage_path', sa.String(length=512), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['job_id'], ['training_jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id', 'artifact_type', name='uq_training_artifacts_job_type')
    )
    with op.batch_alter_table('training_artifacts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_training_artifacts_artifact_type'), ['artifact_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_artifacts_asset_id'), ['asset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_artifacts_job_id'), ['job_id'], unique=False)

    op.create_table('detections',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('revision_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('category_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('x_center', sa.Float(), nullable=False),
    sa.Column('y_center', sa.Float(), nullable=False),
    sa.Column('width', sa.Float(), nullable=False),
    sa.Column('height', sa.Float(), nullable=False),
    sa.Column('metadata_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name='ck_detections_confidence_range'),
    sa.CheckConstraint('height > 0 AND height <= 1', name='ck_detections_height_range'),
    sa.CheckConstraint('width > 0 AND width <= 1', name='ck_detections_width_range'),
    sa.CheckConstraint('x_center >= 0 AND x_center <= 1', name='ck_detections_x_range'),
    sa.CheckConstraint('y_center >= 0 AND y_center <= 1', name='ck_detections_y_range'),
    sa.ForeignKeyConstraint(['category_id'], ['dataset_categories.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['revision_id'], ['annotation_revisions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('detections', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_detections_category_id'), ['category_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_detections_revision_id'), ['revision_id'], unique=False)

    op.create_table('training_inference_jobs',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('training_job_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('dataset_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('artifact_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('worker_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('confidence_threshold', sa.Float(), nullable=False),
    sa.Column('image_size', sa.Integer(), nullable=False),
    sa.Column('input_filename', sa.String(length=255), nullable=False),
    sa.Column('input_mime_type', sa.String(length=64), nullable=False),
    sa.Column('input_storage_path', sa.String(length=512), nullable=False),
    sa.Column('input_asset_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('input_width', sa.Integer(), nullable=False),
    sa.Column('input_height', sa.Integer(), nullable=False),
    sa.Column('result_mime_type', sa.String(length=64), nullable=False),
    sa.Column('result_storage_path', sa.String(length=512), nullable=False),
    sa.Column('result_asset_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('detections_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('assignment_token_hash', sa.String(length=128), nullable=False),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('confidence_threshold >= 0 AND confidence_threshold <= 1', name='ck_training_inference_confidence_range'),
    sa.ForeignKeyConstraint(['artifact_id'], ['training_artifacts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['input_asset_id'], ['assets.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['result_asset_id'], ['assets.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['training_job_id'], ['training_jobs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['worker_id'], ['training_workers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('training_inference_jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_training_inference_jobs_artifact_id'), ['artifact_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_inference_jobs_dataset_id'), ['dataset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_inference_jobs_input_asset_id'), ['input_asset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_inference_jobs_lease_expires_at'), ['lease_expires_at'], unique=False)
        batch_op.create_index('ix_training_inference_jobs_queue', ['status', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_inference_jobs_result_asset_id'), ['result_asset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_inference_jobs_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_inference_jobs_training_job_id'), ['training_job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_inference_jobs_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_inference_jobs_worker_id'), ['worker_id'], unique=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('training_inference_jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_training_inference_jobs_worker_id'))
        batch_op.drop_index(batch_op.f('ix_training_inference_jobs_user_id'))
        batch_op.drop_index(batch_op.f('ix_training_inference_jobs_training_job_id'))
        batch_op.drop_index(batch_op.f('ix_training_inference_jobs_status'))
        batch_op.drop_index(batch_op.f('ix_training_inference_jobs_result_asset_id'))
        batch_op.drop_index('ix_training_inference_jobs_queue')
        batch_op.drop_index(batch_op.f('ix_training_inference_jobs_lease_expires_at'))
        batch_op.drop_index(batch_op.f('ix_training_inference_jobs_input_asset_id'))
        batch_op.drop_index(batch_op.f('ix_training_inference_jobs_dataset_id'))
        batch_op.drop_index(batch_op.f('ix_training_inference_jobs_artifact_id'))

    op.drop_table('training_inference_jobs')
    with op.batch_alter_table('detections', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_detections_revision_id'))
        batch_op.drop_index(batch_op.f('ix_detections_category_id'))

    op.drop_table('detections')
    with op.batch_alter_table('training_artifacts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_training_artifacts_job_id'))
        batch_op.drop_index(batch_op.f('ix_training_artifacts_asset_id'))
        batch_op.drop_index(batch_op.f('ix_training_artifacts_artifact_type'))

    op.drop_table('training_artifacts')
    with op.batch_alter_table('annotation_revisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_annotation_revisions_is_current'))
        batch_op.drop_index(batch_op.f('ix_annotation_revisions_image_id'))

    op.drop_table('annotation_revisions')
    with op.batch_alter_table('training_jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_training_jobs_worker_id'))
        batch_op.drop_index(batch_op.f('ix_training_jobs_user_id'))
        batch_op.drop_index(batch_op.f('ix_training_jobs_status'))
        batch_op.drop_index('ix_training_jobs_queue')
        batch_op.drop_index(batch_op.f('ix_training_jobs_lease_expires_at'))
        batch_op.drop_index(batch_op.f('ix_training_jobs_export_id'))
        batch_op.drop_index(batch_op.f('ix_training_jobs_dataset_id'))

    op.drop_table('training_jobs')
    with op.batch_alter_table('task_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_task_items_task_id'))
        batch_op.drop_index(batch_op.f('ix_task_items_status'))
        batch_op.drop_index(batch_op.f('ix_task_items_lease_expires_at'))
        batch_op.drop_index('ix_task_items_dispatch')

    op.drop_table('task_items')
    with op.batch_alter_table('dataset_images', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dataset_images_source_task_id'))
        batch_op.drop_index('ix_dataset_images_dataset_selected_ordinal')
        batch_op.drop_index(batch_op.f('ix_dataset_images_dataset_id'))
        batch_op.drop_index('ix_dataset_images_dataset_annotation_status')
        batch_op.drop_index(batch_op.f('ix_dataset_images_asset_id'))

    op.drop_table('dataset_images')
    with op.batch_alter_table('dataset_tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dataset_tasks_user_id'))
        batch_op.drop_index(batch_op.f('ix_dataset_tasks_task_type'))
        batch_op.drop_index('ix_dataset_tasks_status_created_at')
        batch_op.drop_index(batch_op.f('ix_dataset_tasks_status'))
        batch_op.drop_index(batch_op.f('ix_dataset_tasks_source_asset_id'))
        batch_op.drop_index(batch_op.f('ix_dataset_tasks_dataset_id'))
        batch_op.drop_index('ix_dataset_tasks_dataset_created_at')

    op.drop_table('dataset_tasks')
    with op.batch_alter_table('dataset_exports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dataset_exports_lease_expires_at'))
        batch_op.drop_index(batch_op.f('ix_dataset_exports_dataset_id'))
        batch_op.drop_index(batch_op.f('ix_dataset_exports_asset_id'))

    op.drop_table('dataset_exports')
    with op.batch_alter_table('dataset_categories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dataset_categories_dataset_id'))

    op.drop_table('dataset_categories')
    with op.batch_alter_table('assets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assets_user_id'))
        batch_op.drop_index(batch_op.f('ix_assets_status'))
        batch_op.drop_index(batch_op.f('ix_assets_sha256'))
        batch_op.drop_index(batch_op.f('ix_assets_kind'))
        batch_op.drop_index(batch_op.f('ix_assets_deleted_at'))
        batch_op.drop_index(batch_op.f('ix_assets_dataset_id'))

    op.drop_table('assets')
    with op.batch_alter_table('refresh_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_refresh_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_refresh_sessions_rotated_to_id'))
        batch_op.drop_index(batch_op.f('ix_refresh_sessions_family_id'))
        batch_op.drop_index(batch_op.f('ix_refresh_sessions_expires_at'))

    op.drop_table('refresh_sessions')
    with op.batch_alter_table('model_profiles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_model_profiles_user_id'))

    op.drop_table('model_profiles')
    with op.batch_alter_table('idempotency_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_idempotency_records_user_id'))
        batch_op.drop_index('ix_idempotency_records_expiry')

    op.drop_table('idempotency_records')
    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_datasets_user_id'))
        batch_op.drop_index(batch_op.f('ix_datasets_status'))

    op.drop_table('datasets')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    with op.batch_alter_table('training_workers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_training_workers_status'))
        batch_op.drop_index(batch_op.f('ix_training_workers_current_job_id'))

    op.drop_table('training_workers')
    with op.batch_alter_table('outbox_events', schema=None) as batch_op:
        batch_op.drop_index('ix_outbox_events_pending')
        batch_op.drop_index(batch_op.f('ix_outbox_events_event_type'))
        batch_op.drop_index(batch_op.f('ix_outbox_events_aggregate_id'))

    op.drop_table('outbox_events')
    # ### end Alembic commands ###
