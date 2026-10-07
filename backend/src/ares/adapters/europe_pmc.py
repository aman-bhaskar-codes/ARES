import httpx
from datetime import datetime, timezone
import logging
from ares.domain.tools import ToolSpec, ToolContext, ToolResult

logger = logging.getLogger(__name__)

class EuropePMCTool:
    def __init__(self):
        self.endpoint = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name="europe_pmc_lookup",
            version="1.0",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10, "maximum": 25}
                },
                "required": ["query"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "pmid": {"type": "string"},
                                "pmcid": {"type": "string"},
                                "doi": {"type": "string"},
                                "isOpenAccess": {"type": "string"},
                                "abstractText": {"type": "string"}
                            }
                        }
                    }
                }
            },
            allowed_modes=["research"],
            allowed_roles=["workspace_member"],
            billing_class="public_free",
            network_target_policy="strict_allowlist",
            timeout_seconds=15.0,
            byte_limit=1024 * 1024,
            result_limit=25,
            idempotent=True,
            evidence_publication_policy="open_access_citation"
        )

    def execute(self, context: ToolContext, inputs: dict) -> ToolResult:
        query = inputs["query"]
        limit = inputs.get("limit", 10)
        
        params = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": limit
        }
        
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(self.endpoint, params=params)
                response.raise_for_status()
                data = response.json()
            
            result_list = data.get("resultList", {}).get("result", [])
            results = []
            
            for r in result_list:
                results.append({
                    "title": r.get("title", ""),
                    "pmid": r.get("pmid", ""),
                    "pmcid": r.get("pmcid", ""),
                    "doi": r.get("doi", ""),
                    "isOpenAccess": r.get("isOpenAccess", "N"),
                    "abstractText": r.get("abstractText", "")
                })
                
            return ToolResult(
                payload={"results": results},
                retrieval_timestamp=datetime.now(timezone.utc),
                capture_timestamp=datetime.now(timezone.utc),
                license="Europe PMC Term of Use",
                attribution="Europe PMC"
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                return ToolResult(error_category="rate_limited", error_message="Europe PMC rate limited.")
            return ToolResult(error_category="unavailable", error_message=str(e))
        except Exception as e:
            logger.exception("Europe PMC query failed")
            return ToolResult(error_category="unavailable", error_message="Europe PMC query failed.")
