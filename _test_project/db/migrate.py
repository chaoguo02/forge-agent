"""Database migration script — auto-generates CREATE TABLE SQL from models."""

import sys
import os

# Ensure project root is on sys.path so we can import src.models
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models import SCHEMAS


def generate_create_table(schema: dict) -> str:
    """Generate a single CREATE TABLE statement from a schema dict.

    Args:
        schema: A dict with "table" (str) and "columns" (dict of name -> type).

    Returns:
        A SQL string ending with a semicolon.
    """
    table_name = schema["table"]
    col_defs = []
    for col_name, col_type in schema["columns"].items():
        col_defs.append(f"    {col_name} {col_type}")
    cols_sql = ",\n".join(col_defs)
    return f"CREATE TABLE IF NOT EXISTS {table_name} (\n{cols_sql}\n);"


def generate_sql(schemas: list[dict] | None = None) -> str:
    """Generate full DDL SQL for all schemas, separated by blank lines.

    Args:
        schemas: List of schema dicts. Defaults to ``SCHEMAS`` from models.

    Returns:
        A complete SQL string with one statement per table.
    """
    if schemas is None:
        schemas = SCHEMAS
    statements = [generate_create_table(s) for s in schemas]
    return "\n\n".join(statements) + "\n"


def main():
    """Print generated DDL SQL to stdout."""
    print(generate_sql())


if __name__ == "__main__":
    main()
