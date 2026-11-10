import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import Scope, traverse_scope

from app.schemas.connections import SchemaInfo, TableSchema
from app.sql.dialects import DatabaseDialect, get_sqlglot_dialect
from app.sql.schemas import SQLValidationResponse

_BLOCKED_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "TruncateTable",
    "Grant",
    "Revoke",
    "Transaction",
    "Commit",
    "Rollback",
    "Command",
    "Pragma",
    "Attach",
    "Detach",
    "Set",
    "Use",
    "Copy",
    "Execute",
    "Into",
    "Lock",
    "LoadData",
    "Analyze",
    "Uncache",
)
_BLOCKED_NODES = tuple(
    node_type
    for name in _BLOCKED_NODE_NAMES
    if isinstance((node_type := getattr(exp, name, None)), type)
)
_BLOCKED_FUNCTIONS = {
    "sqlite": {
        "eval",
        "fts3_tokenizer",
        "load_extension",
        "readfile",
        "writefile",
    },
    "postgresql": {
        "dblink",
        "lo_export",
        "lo_import",
        "nextval",
        "pg_advisory_lock",
        "pg_advisory_xact_lock",
        "pg_advisory_unlock",
        "pg_advisory_unlock_all",
        "pg_cancel_backend",
        "pg_create_logical_replication_slot",
        "pg_create_physical_replication_slot",
        "pg_create_restore_point",
        "pg_drop_replication_slot",
        "pg_log_backend_memory_contexts",
        "pg_logical_emit_message",
        "pg_logical_slot_get_changes",
        "pg_logical_slot_get_binary_changes",
        "pg_ls_logdir",
        "pg_ls_waldir",
        "pg_terminate_backend",
        "pg_notify",
        "pg_read_binary_file",
        "pg_read_file",
        "pg_reload_conf",
        "pg_replication_slot_advance",
        "pg_rotate_logfile",
        "pg_sleep",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_switch_wal",
        "pg_wal_replay_pause",
        "pg_wal_replay_resume",
        "setseed",
        "set_config",
        "setval",
    },
}
_MAX_ERRORS = 20


def _identifier_key(value: str, quoted: bool, dialect: DatabaseDialect) -> str:
    if dialect == "postgresql" and quoted:
        return value
    return value.casefold()


def _catalog_identifier_key(value: str, dialect: DatabaseDialect) -> str:
    return value if dialect == "postgresql" else value.casefold()


def _table_catalog(
    schemas: list[SchemaInfo],
    dialect: DatabaseDialect,
) -> dict[tuple[str, str], tuple[str, TableSchema]]:
    catalog: dict[tuple[str, str], tuple[str, TableSchema]] = {}
    for schema in schemas:
        for table in schema.tables:
            key = (
                _catalog_identifier_key(schema.name, dialect),
                _catalog_identifier_key(table.name, dialect),
            )
            catalog[key] = (schema.name, table)
    return catalog


def _lookup_table(
    table: exp.Table,
    catalog: dict[tuple[str, str], tuple[str, TableSchema]],
    dialect: DatabaseDialect,
) -> tuple[str, TableSchema] | None:
    if not isinstance(table.this, exp.Identifier):
        return None
    name = _identifier_key(
        table.name,
        bool(table.this.args.get("quoted")),
        dialect,
    )
    schema_identifier = table.args.get("db")
    if isinstance(schema_identifier, exp.Identifier):
        schema = _identifier_key(
            schema_identifier.this,
            bool(schema_identifier.args.get("quoted")),
            dialect,
        )
        return catalog.get((schema, name))
    matches = [
        value
        for (_, table_key), value in catalog.items()
        if table_key == name
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _source_columns(source: object) -> set[str] | None:
    if isinstance(source, exp.Table):
        return None
    if not isinstance(source, Scope):
        return None

    expressions = getattr(source.expression, "expressions", [])
    output: set[str] = set()
    for item in expressions:
        if isinstance(item, exp.Star):
            return None
        if isinstance(item, exp.Alias):
            output.add(item.alias.casefold())
        elif isinstance(item, exp.Column):
            output.add(item.name.casefold())
    return output


def _source_table(
    source: object,
    catalog: dict[tuple[str, str], tuple[str, TableSchema]],
    dialect: DatabaseDialect,
) -> tuple[str, TableSchema] | None:
    if isinstance(source, exp.Table):
        return _lookup_table(source, catalog, dialect)
    return None


def _validation_errors(
    expression: exp.Expression,
    schemas: list[SchemaInfo],
    dialect: DatabaseDialect,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    catalog = _table_catalog(schemas, dialect)
    scopes = list(traverse_scope(expression))
    all_aliases: dict[str, list[object]] = {}

    for scope in scopes:
        for alias, source in scope.sources.items():
            all_aliases.setdefault(alias.casefold(), []).append(source)

    used_tables: set[str] = set()
    validated_tables: dict[int, tuple[str, TableSchema]] = {}
    for scope in scopes:
        for source in scope.sources.values():
            if not isinstance(source, exp.Table) or id(source) in validated_tables:
                continue
            match = _lookup_table(source, catalog, dialect)
            if match is None:
                if not isinstance(source.this, exp.Identifier):
                    errors.append("Table-valued functions and unsupported table sources are not allowed.")
                else:
                    errors.append(f"Table '{source.name}' is not present in the connected database schema.")
                continue
            schema_name, table_schema = match
            validated_tables[id(source)] = match
            used_tables.add(
                table_schema.name
                if dialect == "sqlite"
                else f"{schema_name}.{table_schema.name}"
            )

    for scope in scopes:
        select_aliases = {
            item.alias.casefold()
            for item in getattr(scope.expression, "expressions", [])
            if isinstance(item, exp.Alias)
        }
        local_sources: list[object] = []
        seen_sources: set[int] = set()
        for source in scope.sources.values():
            if id(source) not in seen_sources:
                local_sources.append(source)
                seen_sources.add(id(source))

        for column in scope.columns:
            if column.name == "*":
                continue
            column_name = _identifier_key(
                column.name,
                bool(column.this.args.get("quoted")),
                dialect,
            )
            qualifier = column.table.casefold()
            if not qualifier and column_name in select_aliases:
                continue

            if qualifier:
                candidate_sources = [
                    source
                    for source in local_sources
                    if any(
                        alias.casefold() == qualifier
                        for alias, value in scope.sources.items()
                        if value is source
                    )
                ]
                if not candidate_sources:
                    candidate_sources = all_aliases.get(qualifier, [])
                if len({id(source) for source in candidate_sources}) != 1:
                    errors.append(
                        f"Column qualifier '{column.table}' is not present or is ambiguous."
                    )
                    continue
                source = candidate_sources[0]
                matched_table = _source_table(source, catalog, dialect)
                if matched_table is not None:
                    columns = {
                        _catalog_identifier_key(column_schema.name, dialect)
                        for column_schema in matched_table[1].columns
                    }
                    if column_name not in columns:
                        errors.append(
                            f"Column '{column.name}' is not present in table '{matched_table[1].name}'."
                        )
                else:
                    output_columns = _source_columns(source)
                    if output_columns is not None and column_name not in output_columns:
                        errors.append(
                            f"Column '{column.name}' is not projected by '{column.table}'."
                        )
                continue

            matching_sources: list[object] = []
            for source in local_sources:
                matched_table = _source_table(source, catalog, dialect)
                if matched_table is not None:
                    available = {
                        _catalog_identifier_key(column_schema.name, dialect)
                        for column_schema in matched_table[1].columns
                    }
                    if column_name in available:
                        matching_sources.append(source)
                else:
                    projected = _source_columns(source)
                    if projected is not None and column_name in projected:
                        matching_sources.append(source)
            unique_sources = {id(source) for source in matching_sources}
            if len(unique_sources) == 0:
                errors.append(f"Column '{column.name}' is not present in the available schema.")
            elif len(unique_sources) > 1:
                errors.append(
                    f"Column '{column.name}' is ambiguous; qualify it with a table name."
                )

    return list(dict.fromkeys(errors))[:_MAX_ERRORS], sorted(used_tables)


def validate_read_only_sql(
    sql_query: str,
    database_dialect: DatabaseDialect,
    schemas: list[SchemaInfo],
) -> SQLValidationResponse:
    dialect_name = get_sqlglot_dialect(database_dialect)
    try:
        parsed_statements = sqlglot.parse(sql_query, read=dialect_name)
    except ParseError as exc:
        return SQLValidationResponse(
            is_valid=False,
            database_dialect=database_dialect,
            query_type=None,
            validation_errors=[f"SQL could not be parsed: {str(exc).splitlines()[0]}"],
            tables_used=[],
        )

    statements = [statement for statement in parsed_statements if statement is not None]
    if len(statements) != 1:
        return SQLValidationResponse(
            is_valid=False,
            database_dialect=database_dialect,
            query_type=None,
            validation_errors=["Exactly one SQL statement is allowed."],
            tables_used=[],
        )

    expression = statements[0]
    allowed_query_types = (
        exp.Select,
        exp.Union,
        exp.Intersect,
        exp.Except,
        exp.Subquery,
    )
    if not isinstance(expression, allowed_query_types) or any(
        not isinstance(query, allowed_query_types)
        for query in expression.find_all(exp.Query)
    ):
        return SQLValidationResponse(
            is_valid=False,
            database_dialect=database_dialect,
            query_type=type(expression).__name__,
            validation_errors=["Only read-only SELECT queries are allowed."],
            tables_used=[],
        )

    errors: list[str] = []
    if any(
        isinstance(node, exp.Select) and not node.expressions
        for node in expression.walk()
    ):
        errors.append("Each SELECT must include at least one result expression.")
    if any(isinstance(node, _BLOCKED_NODES) for node in expression.walk()):
        errors.append("The query contains a write, administrative, transaction, or locking operation.")
    if expression.find(exp.Into) is not None:
        errors.append("SELECT INTO is not allowed.")
    if expression.find(exp.Lock) is not None:
        errors.append("Locking clauses are not allowed.")

    blocked_functions = _BLOCKED_FUNCTIONS[database_dialect]
    for function in expression.find_all(exp.Func):
        function_name = function.name.casefold()
        if function_name in blocked_functions:
            errors.append(f"Function '{function.name}' is not allowed.")
    schema_errors, tables_used = _validation_errors(expression, schemas, database_dialect)
    errors.extend(schema_errors)

    return SQLValidationResponse(
        is_valid=not errors,
        database_dialect=database_dialect,
        query_type=type(expression).__name__,
        validation_errors=list(dict.fromkeys(errors))[:_MAX_ERRORS],
        tables_used=tables_used,
    )
