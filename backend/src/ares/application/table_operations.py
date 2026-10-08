import pandas as pd
import logging
from ares.domain.tools import ToolSpec, ToolContext, ToolResult

logger = logging.getLogger(__name__)

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

    def execute(self, context: ToolContext, inputs: dict) -> ToolResult:
        dataset = inputs["dataset"]
        operation = inputs["operation"]
        params = inputs["params"]
        
        if len(dataset) > 10000:
            return ToolResult(error_category="invalid_input", error_message="Dataset too large for local operations.")
            
        try:
            df = pd.DataFrame(dataset)
            result_df = df
            
            if operation == "filter":
                column = params.get("column")
                operator = params.get("operator")
                value = params.get("value")
                
                if operator == "equals":
                    result_df = df[df[column] == value]
                elif operator == "greater_than":
                    result_df = df[df[column] > value]
                elif operator == "less_than":
                    result_df = df[df[column] < value]
                else:
                    return ToolResult(error_category="invalid_input", error_message="Unsupported operator.")
                    
            elif operation == "group":
                group_by = params.get("group_by")
                agg_col = params.get("aggregate_column")
                agg_func = params.get("aggregate_function", "sum")
                
                if agg_func not in ["sum", "mean", "count", "max", "min"]:
                    return ToolResult(error_category="invalid_input", error_message="Unsupported aggregate function.")
                
                result_df = df.groupby(group_by)[agg_col].agg(agg_func).reset_index()
                
            elif operation == "aggregate":
                # similar to group but without group_by
                agg_col = params.get("aggregate_column")
                agg_func = params.get("aggregate_function", "sum")
                
                if agg_func == "sum":
                    val = df[agg_col].sum()
                elif agg_func == "mean":
                    val = df[agg_col].mean()
                elif agg_func == "count":
                    val = df[agg_col].count()
                else:
                    return ToolResult(error_category="invalid_input", error_message="Unsupported aggregate function.")
                
                result_df = pd.DataFrame([{f"{agg_func}_{agg_col}": val}])
                
            elif operation == "join":
                return ToolResult(error_category="unsupported", error_message="Join is not fully implemented yet.")
                
            results = result_df.to_dict(orient="records")
            if len(results) > 1000:
                results = results[:1000] # Cap results
                
            return ToolResult(payload={"results": results})
        except KeyError as e:
            return ToolResult(error_category="invalid_input", error_message=f"Missing column: {str(e)}")
        except Exception:
            logger.exception("Table operation failed")
            return ToolResult(error_category="unavailable", error_message="Calculation error.")
