from ares.domain.tools import ToolSpec, ToolContext, ToolResult
import logging

logger = logging.getLogger(__name__)

class SearXNGTool:
    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name="searxng_search",
            version="1.0",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10}
                },
                "required": ["query"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "results": {"type": "array"}
                }
            },
            allowed_modes=["research"],
            allowed_roles=["workspace_member"],
            billing_class="local",
            network_target_policy="authorized_sources_only",
            timeout_seconds=10.0,
            byte_limit=1024 * 1024,
            result_limit=10,
            idempotent=True,
            evidence_publication_policy="public_domain_attribution"
        )
        
    def execute(self, context: ToolContext, inputs: dict) -> ToolResult:
        # Wrapper for existing SearXNG logic
        return ToolResult(payload={"results": []})

class CrossrefTool:
    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name="crossref_search",
            version="1.0",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"results": {"type": "array"}}},
            allowed_modes=["research"],
            allowed_roles=["workspace_member"],
            billing_class="public_free",
            network_target_policy="authorized_sources_only",
            timeout_seconds=10.0,
            byte_limit=1024 * 1024,
            result_limit=10,
            idempotent=True,
            evidence_publication_policy="public_domain_attribution"
        )
        
    def execute(self, context: ToolContext, inputs: dict) -> ToolResult:
        # Wrapper for existing Crossref logic
        return ToolResult(payload={"results": []})

class ArxivTool:
    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name="arxiv_search",
            version="1.0",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"results": {"type": "array"}}},
            allowed_modes=["research"],
            allowed_roles=["workspace_member"],
            billing_class="public_free",
            network_target_policy="authorized_sources_only",
            timeout_seconds=10.0,
            byte_limit=1024 * 1024,
            result_limit=10,
            idempotent=True,
            evidence_publication_policy="public_domain_attribution"
        )
        
    def execute(self, context: ToolContext, inputs: dict) -> ToolResult:
        # Wrapper for existing Arxiv logic
        return ToolResult(payload={"results": []})

class GitHubTool:
    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name="github_facts",
            version="1.0",
            input_schema={"type": "object", "properties": {"repo": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"results": {"type": "array"}}},
            allowed_modes=["research"],
            allowed_roles=["workspace_member"],
            billing_class="public_free",
            network_target_policy="authorized_sources_only",
            timeout_seconds=10.0,
            byte_limit=1024 * 1024,
            result_limit=10,
            idempotent=True,
            evidence_publication_policy="public_domain_attribution"
        )
        
    def execute(self, context: ToolContext, inputs: dict) -> ToolResult:
        # Wrapper for existing GitHub logic
        return ToolResult(payload={"results": []})
