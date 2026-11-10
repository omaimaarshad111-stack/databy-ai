import pytest

from app.schemas.connections import (
    ColumnSchema,
    ForeignKeySchema,
    SchemaInfo,
    TableSchema,
)
from app.sql.validator import validate_read_only_sql


@pytest.fixture
def sqlite_schema() -> list[SchemaInfo]:
    return [
        SchemaInfo(
            name="main",
            tables=[
                TableSchema(
                    name="customers",
                    columns=[
                        ColumnSchema(name="id", data_type="INTEGER", nullable=False),
                        ColumnSchema(name="name", data_type="TEXT", nullable=False),
                    ],
                    primary_key=["id"],
                    foreign_keys=[],
                    unique_constraints=[],
                    indexes=[],
                ),
                TableSchema(
                    name="orders",
                    columns=[
                        ColumnSchema(name="id", data_type="INTEGER", nullable=False),
                        ColumnSchema(name="customer_id", data_type="INTEGER", nullable=False),
                        ColumnSchema(name="total", data_type="REAL", nullable=False),
                    ],
                    primary_key=["id"],
                    foreign_keys=[
                        ForeignKeySchema(
                            columns=["customer_id"],
                            referred_table="customers",
                            referred_columns=["id"],
                        )
                    ],
                    unique_constraints=[],
                    indexes=[],
                ),
            ],
        )
    ]


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id, name FROM customers WHERE id > 1 ORDER BY name LIMIT 5",
        "SELECT customer_id, SUM(total) AS amount FROM orders GROUP BY customer_id ORDER BY amount DESC LIMIT 10",
        "WITH customer_orders AS (SELECT customer_id, total FROM orders) SELECT customer_id, SUM(total) AS amount FROM customer_orders GROUP BY customer_id",
        "SELECT c.name, (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id) AS order_count FROM customers c",
        "SELECT id FROM customers UNION SELECT customer_id FROM orders",
        "SELECT 1",
    ],
)
def test_read_only_select_queries_validate(query: str, sqlite_schema: list[SchemaInfo]) -> None:
    result = validate_read_only_sql(query, "sqlite", sqlite_schema)

    assert result.is_valid, result.validation_errors


@pytest.mark.parametrize(
    ("query", "expected_error"),
    [
        ("SELECT FROM customers", "at least one result expression"),
        ("VALUES (1)", "Only read-only"),
        ("SELECT id FROM customers; SELECT id FROM orders", "Exactly one"),
        ("INSERT INTO customers (name) VALUES ('x')", "Only read-only"),
        ("UPDATE customers SET name = 'x'", "Only read-only"),
        ("DELETE FROM customers", "Only read-only"),
        ("DROP TABLE customers", "Only read-only"),
        ("ALTER TABLE customers ADD COLUMN x TEXT", "Only read-only"),
        ("CREATE TABLE new_table (id INTEGER)", "Only read-only"),
        ("ATTACH DATABASE 'other.db' AS other", "Only read-only"),
        ("PRAGMA writable_schema = ON", "SQL could not be parsed"),
        ("SET ROLE admin", "Only read-only"),
        ("SELECT id INTO copied FROM customers", "SELECT INTO"),
        ("SELECT id FROM customers FOR UPDATE", "Locking"),
        (
            "WITH changed AS (DELETE FROM customers RETURNING id) SELECT id FROM changed",
            "write, administrative",
        ),
        ("SELECT load_extension('extension')", "Function 'load_extension'"),
        ("SELECT readfile('/etc/passwd')", "Function 'readfile'"),
        ("SELECT missing FROM customers", "Column 'missing'"),
        ("SELECT id FROM missing_table", "Table 'missing_table'"),
        ("SELECT id FROM customers; DROP TABLE customers", "Exactly one"),
    ],
)
def test_unsafe_or_unknown_queries_are_rejected(
    query: str,
    expected_error: str,
    sqlite_schema: list[SchemaInfo],
) -> None:
    result = validate_read_only_sql(query, "sqlite", sqlite_schema)

    assert not result.is_valid
    assert any(expected_error in error for error in result.validation_errors)


def test_ambiguous_unqualified_column_is_rejected(sqlite_schema: list[SchemaInfo]) -> None:
    sqlite_schema[0].tables[1].columns.append(
        ColumnSchema(name="name", data_type="TEXT", nullable=True)
    )

    result = validate_read_only_sql(
        "SELECT name FROM customers JOIN orders ON customers.id = orders.customer_id",
        "sqlite",
        sqlite_schema,
    )

    assert not result.is_valid
    assert any("ambiguous" in error for error in result.validation_errors)


def test_postgresql_dialect_and_unsafe_functions_are_checked() -> None:
    pg_schema = [
        SchemaInfo(
            name="public",
            tables=[
                TableSchema(
                    name="customers",
                    columns=[
                        ColumnSchema(name="id", data_type="INTEGER", nullable=False),
                        ColumnSchema(name="name", data_type="TEXT", nullable=False),
                    ],
                    primary_key=["id"],
                    foreign_keys=[],
                    unique_constraints=[],
                    indexes=[],
                )
            ],
        )
    ]

    valid = validate_read_only_sql(
        "SELECT c.name FROM public.customers AS c WHERE c.id > 0 LIMIT 5",
        "postgresql",
        pg_schema,
    )
    unsafe = validate_read_only_sql(
        "SELECT pg_read_file('/etc/passwd')",
        "postgresql",
        pg_schema,
    )

    assert valid.is_valid
    assert valid.tables_used == ["public.customers"]
    assert not unsafe.is_valid
    assert any("pg_read_file" in error for error in unsafe.validation_errors)


def test_postgresql_quoted_identifiers_preserve_case() -> None:
    pg_schema = [
        SchemaInfo(
            name="public",
            tables=[
                TableSchema(
                    name="Customers",
                    columns=[
                        ColumnSchema(name="DisplayName", data_type="TEXT", nullable=False)
                    ],
                    primary_key=[],
                    foreign_keys=[],
                    unique_constraints=[],
                    indexes=[],
                )
            ],
        )
    ]

    quoted = validate_read_only_sql(
        'SELECT "DisplayName" FROM "Customers"',
        "postgresql",
        pg_schema,
    )
    unquoted_column = validate_read_only_sql(
        'SELECT displayname FROM "Customers"',
        "postgresql",
        pg_schema,
    )
    unquoted_table = validate_read_only_sql(
        "SELECT displayname FROM Customers",
        "postgresql",
        pg_schema,
    )

    assert quoted.is_valid
    assert not unquoted_column.is_valid
    assert not unquoted_table.is_valid
    assert any("displayname" in error for error in unquoted_column.validation_errors)
