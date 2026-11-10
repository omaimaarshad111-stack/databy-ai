from decimal import Decimal
from numbers import Number

from app.sql.schemas import SQLExecutionResponse


def summarize_execution(result: SQLExecutionResponse) -> str:
    if result.status != "success":
        return result.error or "The query could not be completed."
    if result.row_count == 0:
        return "The query completed successfully and returned no rows."

    names = [column.name for column in result.columns]
    summary = (
        f"The query returned {result.row_count} row(s) across {len(names)} "
        f"column(s): {', '.join(names) if names else 'no named columns'}."
    )
    if result.truncated:
        summary += " The displayed results were truncated to the configured limit."

    numeric_summaries: list[str] = []
    for column_index, name in enumerate(names):
        values = [
            row[column_index]
            for row in result.rows
            if column_index < len(row)
            and isinstance(row[column_index], (Number, Decimal))
            and not isinstance(row[column_index], bool)
        ]
        if values:
            numeric_summaries.append(
                f"{name}: minimum {min(values)}, maximum {max(values)}"
            )
    if numeric_summaries:
        summary += " Numeric ranges in the returned rows: " + "; ".join(
            numeric_summaries[:5]
        ) + "."
    return summary
