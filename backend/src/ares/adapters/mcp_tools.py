from ares.domain.tools import ToolSpec, ToolContext, ToolResult
import logging

logger = logging.getLogger(__name__)

class MCPCompatibilityTool:
    """
    An optional compatibility adapter to route MCP tools through the same
    registry, budget, and evidence policy as native tools.
    """
    def __init__(self, mcp_name: str, input_schema: dict, output_schema: dict):
        self.mcp_name = mcp_name
        self._input_schema = input_schema
        self._output_schema = output_schema

    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name=f"mcp_{self.mcp_name}",
            version="1.0",
            input_schema=self._input_schema,
            output_schema=self._output_schema,
            allowed_modes=["research", "comparison"],
            allowed_roles=["workspace_member"],
            billing_class="local",
            network_target_policy="strict_allowlist", # No arbitrary server URLs
            timeout_seconds=30.0,
            byte_limit=1024 * 1024 * 5, # 5 MB
            result_limit=100,
            idempotent=False,
            evidence_publication_policy="private"
        )
        
    def execute(self, context: ToolContext, inputs: dict) -> ToolResult:
        # MCP server URL / transport would be resolved here via an allowlisted catalog.
        # No session-token forwarding allowed.
        # This is a stub adapter placeholder.
        return ToolResult(
            error_category="unsupported",
            error_message="MCP connection not yet enabled by operator."
        )
