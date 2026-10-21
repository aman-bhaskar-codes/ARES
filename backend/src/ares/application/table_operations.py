from __future__ import annotations

import logging
from typing import Any

from ares.domain.tools import ToolContext, ToolResult, ToolSpec

logger = logging.getLogger(__name__)

def _execute_pure_python(dataset: list[dict[str, Any]], operation: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    if operation == "filter":
        col = params.get("column")
        op = params.get("operator")
        val = params.get("value")
        filtered = []
        for row in dataset:
            row_val = row.get(col)
            if op == "equals" and row_val == val:
                filtered.append(row)
            elif op == "greater_than" and row_val is not None and row_val > val:
                filtered.append(row)
            elif op == "less_than" and row_val is not None and row_val < val:
                filtered.append(row)
            elif op not in {"equals", "greater_than", "less_than"}:
                raise ValueError("Unsupported operator.")
        return filtered

    elif operation == "group":
        group_by = params.get("group_by")
        agg_col = params.get("aggregate_column")
        agg_func = params.get("aggregate_function", "sum")
        if agg_func not in ["sum", "mean", "count", "max", "min"]:
            raise ValueError("Unsupported aggregate function.")

        groups: dict[Any, list[float]] = {}
        for row in dataset:
            key = row.get(group_by)
            v = row.get(agg_col)
            if v is not None:
                try:
                    num_val = float(v)
                    groups.setdefault(key, []).append(num_val)
                except (ValueError, TypeError):
                    pass

        results = []
        for key, vals in groups.items():
            if agg_func == "sum":
                agg_val = sum(vals)
            elif agg_func == "mean":
                agg_val = sum(vals) / len(vals) if vals else 0.0
            elif agg_func == "count":
                agg_val = len(vals)
            elif agg_func == "max":
                agg_val = max(vals) if vals else 0.0
            elif agg_func == "min":
                agg_val = min(vals) if vals else 0.0
            results.append({group_by: key, agg_col: agg_val})
        return results

    elif operation == "aggregate":
        agg_col = params.get("aggregate_column")
        agg_func = params.get("aggregate_function", "sum")
        vals = []
        for row in dataset:
            v = row.get(agg_col)
            if v is not None:
                try:
                    vals.append(float(v))
                except (ValueError, TypeError):
                    pass
        if agg_func == "sum":
            val = sum(vals)
        elif agg_func == "mean":
            val = sum(vals) / len(vals) if vals else 0.0
        elif agg_func == "count":
            val = len(vals)
        elif agg_func == "max":
            val = max(vals) if vals else 0.0
        elif agg_func == "min":
            val = min(vals) if vals else 0.0
        else:
            raise ValueError("Unsupported aggregate function.")
        return [{f"{agg_func}_{agg_col}": val}]

    elif operation == "join":
        raise NotImplementedError("Join is not fully implemented yet.")
    raise ValueError(f"Unsupported operation: {operation}")


class TableOperationsTool:
    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name="table_operations",
            version="1.0",
            input_schema={
                "type": "object",
                "properties": {
                    "dataset": {
                        "type": "array",
                        "items": {"type": "object"}
                    },
                    "operation": {
                        "type": "string",
                        "enum": ["filter", "group", "aggregate", "join"]
                    },
                    "params": {"type": "object"}
                },
                "required": ["dataset", "operation", "params"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {"type": "object"}
                    }
                }
            },
            allowed_modes=["dataset_analysis"],
            allowed_roles=["workspace_member"],
            billing_class="local",
            network_target_policy="none",
            timeout_seconds=5.0,
            byte_limit=1024 * 1024 * 5,  # 5 MB
            result_limit=1000,
            idempotent=True,
            evidence_publication_policy="local_calculation"
        )

    def execute(self, context: ToolContext, inputs: dict[str, Any]) -> ToolResult:
        dataset = inputs.get("dataset", [])
        operation = inputs.get("operation", "")
        params = inputs.get("params", {})

        if len(dataset) > 10000:
            return ToolResult(error_category="invalid_input", error_message="Dataset too large for local operations.")

        try:
            results = _execute_pure_python(dataset, operation, params)
            if len(results) > 1000:
                results = results[:1000]
            return ToolResult(payload={"results": results})
        except (ValueError, KeyError) as e:
            return ToolResult(error_category="invalid_input", error_message=str(e))
        except NotImplementedError as e:
            return ToolResult(error_category="unsupported", error_message=str(e))
        except Exception:
            logger.exception("Table operation failed")
            return ToolResult(error_category="unavailable", error_message="Calculation error.")


def table_view_to_dataset(table: Any) -> list[dict[str, Any]]:
    """Convert a stored TableView or Docling table structure into a tabular dataset.

    Extracts column headers and maps row values into standard records for TableOperationsTool.
    """
    if not hasattr(table, "cells") or not table.cells:
        return []

    cells_by_pos: dict[tuple[int, int], Any] = {
        (cell.row, cell.column): cell for cell in table.cells
    }
    num_rows = getattr(table, "rows", 0)
    num_cols = getattr(table, "columns", 0)
    if num_rows <= 0 or num_cols <= 0:
        max_r = max((r for r, _ in cells_by_pos.keys()), default=0) + 1
        max_c = max((c for _, c in cells_by_pos.keys()), default=0) + 1
        num_rows = max(num_rows, max_r)
        num_cols = max(num_cols, max_c)

    # Determine headers from row 0 or is_header cells
    headers: list[str] = []
    has_header_row = any(
        getattr(cells_by_pos.get((0, col)), "is_header", False)
        or bool(getattr(cells_by_pos.get((0, col)), "raw_text", ""))
        for col in range(num_cols)
    )

    data_start_row = 1 if has_header_row and num_rows > 1 else 0
    for col in range(num_cols):
        if has_header_row and (0, col) in cells_by_pos:
            header_name = str(cells_by_pos[(0, col)].raw_text or "").strip()
            headers.append(header_name or f"col_{col + 1}")
        else:
            headers.append(f"col_{col + 1}")

    records: list[dict[str, Any]] = []
    for row in range(data_start_row, num_rows):
        record: dict[str, Any] = {}
        row_has_data = False
        for col in range(num_cols):
            header = headers[col] if col < len(headers) else f"col_{col + 1}"
            cell = cells_by_pos.get((row, col))
            if cell is not None:
                val: Any = getattr(cell, "normalized_value", None)
                if val is None:
                    raw_text = str(getattr(cell, "raw_text", "") or "").strip()
                    # Try automatic numeric conversion
                    try:
                        if "." in raw_text:
                            val = float(raw_text)
                        else:
                            val = int(raw_text)
                    except ValueError:
                        val = raw_text
                record[header] = val
                if str(val).strip():
                    row_has_data = True
            else:
                record[header] = None
        if row_has_data:
            records.append(record)

    return records

