from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.database_targets.exceptions import TargetConnectionError
from app.schemas.connections import (
    ColumnSchema,
    ForeignKeySchema,
    IndexSchema,
    SchemaInfo,
    TableSchema,
)


def inspect_database_schema(engine: Engine) -> list[SchemaInfo]:
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            dialect_name = connection.dialect.name
            schemas = inspector.get_schema_names() if dialect_name == "postgresql" else ["main"]
            if dialect_name == "postgresql":
                schemas = [
                    schema
                    for schema in schemas
                    if schema not in {"information_schema", "pg_catalog"}
                    and not schema.startswith("pg_")
                ]

            schema_results: list[SchemaInfo] = []
            for schema_name in sorted(schemas):
                tables = []
                for table_name in sorted(inspector.get_table_names(schema=schema_name if dialect_name == "postgresql" else None)):
                    qualified_schema = schema_name if dialect_name == "postgresql" else None
                    columns = [
                        ColumnSchema(
                            name=column["name"],
                            data_type=str(column["type"]),
                            nullable=bool(column["nullable"]),
                            default=(
                                str(column["default"])
                                if column.get("default") is not None
                                else None
                            ),
                        )
                        for column in inspector.get_columns(table_name, schema=qualified_schema)
                    ]
                    primary_key = inspector.get_pk_constraint(
                        table_name, schema=qualified_schema
                    ).get("constrained_columns") or []
                    foreign_keys = [
                        ForeignKeySchema(
                            name=foreign_key.get("name"),
                            columns=foreign_key.get("constrained_columns") or [],
                            referred_schema=foreign_key.get("referred_schema"),
                            referred_table=foreign_key.get("referred_table") or "",
                            referred_columns=foreign_key.get("referred_columns") or [],
                        )
                        for foreign_key in inspector.get_foreign_keys(
                            table_name, schema=qualified_schema
                        )
                    ]
                    unique_constraints = [
                        constraint.get("column_names") or []
                        for constraint in inspector.get_unique_constraints(
                            table_name, schema=qualified_schema
                        )
                    ]
                    indexes = [
                        IndexSchema(
                            name=index.get("name") or "",
                            columns=[
                                column
                                for column in index.get("column_names") or []
                                if column is not None
                            ],
                            unique=bool(index.get("unique")),
                        )
                        for index in inspector.get_indexes(table_name, schema=qualified_schema)
                    ]
                    tables.append(
                        TableSchema(
                            name=table_name,
                            columns=columns,
                            primary_key=primary_key,
                            foreign_keys=foreign_keys,
                            unique_constraints=unique_constraints,
                            indexes=indexes,
                        )
                    )
                schema_results.append(SchemaInfo(name=schema_name, tables=tables))
            return schema_results
    except (SQLAlchemyError, NotImplementedError, ValueError):
        raise TargetConnectionError(
            "The database schema could not be inspected."
        ) from None
