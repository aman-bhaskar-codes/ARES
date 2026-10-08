import logging
import jsonschema
from typing import Dict, Any
from ares.domain.tools import ToolSpec, ToolContext, ToolResult
from ares.ports.tools import Tool
from ares.application.repository import Repository

logger = logging.getLogger(__name__)

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        spec = tool.get_spec()
        self._tools[spec.name] = tool

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_all_specs(self) -> list[ToolSpec]:
        return [t.get_spec() for t in self._tools.values()]

class ToolExecutor:
    def __init__(self, registry: ToolRegistry, repository: Repository):
        self.registry = registry
        self.repository = repository

    def _validate_schema(self, instance: Any, schema: dict) -> str | None:
        try:
            jsonschema.validate(instance=instance, schema=schema)
            return None
        except jsonschema.ValidationError as e:
            return str(e)

    def execute_tool(self, name: str, context: ToolContext, inputs: dict) -> ToolResult:
        tool = self.registry.get_tool(name)
        if not tool:
            return ToolResult(
                error_category="unsupported",
                error_message=f"Tool '{name}' is not registered."
            )

        spec = tool.get_spec()

        # Validate workspace membership (via repository)
        if not self.repository.check_workspace_membership(context.workspace_id, "execute_tool"): # placeholder for actual auth check
            return ToolResult(
                error_category="not_authorized",
                error_message="Not authorized for this workspace."
            )

        # Validate inputs against schema
        validation_error = self._validate_schema(inputs, spec.input_schema)
        if validation_error:
            return ToolResult(
                error_category="invalid_input",
                error_message=f"Invalid inputs: {validation_error}"
            )

        try:
            # Execute tool
            result = tool.execute(context, inputs)
            
            # Validate output against schema
            if result.error_category is None:
                output_validation_error = self._validate_schema(result.payload, spec.output_schema)
                if output_validation_error:
                    logger.error(f"Tool {name} returned invalid output schema: {output_validation_error}")
                    return ToolResult(
                        error_category="unavailable",
                        error_message="Tool returned invalid data format."
                    )
            
            return result
        except Exception:
            logger.exception(f"Unhandled exception executing tool {name}")
            return ToolResult(
                error_category="unavailable",
                error_message="An internal error occurred during tool execution."
            )
