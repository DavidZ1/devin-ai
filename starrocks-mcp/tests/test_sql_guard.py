import pytest

from starrocks_mcp.sql_guard import SqlRejected, validate_select


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH cte AS (SELECT 1 AS n) SELECT n FROM cte",
        "SELECT 1 UNION SELECT 2",
        "/* read only */ SELECT id FROM analytics.items",
        "SELECT id FROM analytics.items",
    ],
)
def test_accepts_read_only_queries(sql):
    validate_select(sql, allowed_dbs={"analytics"})


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        "DELETE FROM t",
        "DROP TABLE t",
        "CREATE TABLE t (a INT)",
        "ALTER TABLE t ADD COLUMN b INT",
        "TRUNCATE TABLE t",
        "SET SESSION query_timeout = 1",
        "SELECT 1; DROP TABLE t",
        "SELECT * INTO OUTFILE 'result.csv' FROM t",
        "not valid sql !!!",
    ],
)
def test_rejects_writes_and_invalid_sql(sql):
    with pytest.raises(SqlRejected):
        validate_select(sql)


def test_rejects_system_database():
    with pytest.raises(SqlRejected, match="系统数据库"):
        validate_select("SELECT * FROM information_schema.tables")


def test_rejects_database_outside_allowlist():
    with pytest.raises(SqlRejected, match="不在允许列表"):
        validate_select("SELECT * FROM other_db.items", allowed_dbs={"analytics"})


def test_unqualified_table_needs_database_with_allowlist():
    with pytest.raises(SqlRejected, match="指定数据库"):
        validate_select("SELECT * FROM items", allowed_dbs={"analytics"})


def test_unqualified_table_uses_default_database():
    validate_select("SELECT * FROM items", default_db="analytics", allowed_dbs={"analytics"})


def test_cte_alias_is_not_mistaken_for_table():
    validate_select(
        "WITH staged AS (SELECT 1 AS id) SELECT id FROM staged",
        allowed_dbs={"analytics"},
    )


def test_qualified_table_cannot_bypass_allowlist_with_cte_name():
    with pytest.raises(SqlRejected, match="不在允许列表"):
        validate_select(
            "WITH items AS (SELECT 1) SELECT * FROM secret.items",
            default_db="analytics",
            allowed_dbs={"analytics"},
        )


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT * FROM FILES("path"="data.csv")',
        (
            'SELECT * FROM analytics.items '
            'JOIN FILES("path"="data.csv") AS f ON 1 = 1'
        ),
        'SELECT * FROM (SELECT * FROM FILES("path"="data.csv")) AS source',
    ],
)
def test_rejects_table_functions(sql):
    with pytest.raises(SqlRejected, match="表函数"):
        validate_select(
            sql,
            default_db="analytics",
            allowed_dbs={"analytics"},
        )


def test_rejects_non_default_catalog():
    with pytest.raises(SqlRejected, match="外部 catalog"):
        validate_select(
            "SELECT * FROM hive_cat.db.items",
            allowed_dbs={"db"},
        )


def test_allows_default_catalog_with_allowed_database():
    validate_select(
        "SELECT * FROM default_catalog.analytics.items",
        allowed_dbs={"analytics"},
    )


def test_trailing_semicolon_is_allowed_but_empty_statement_is_ignored():
    validate_select("SELECT 1;")
