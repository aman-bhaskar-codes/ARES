import httpx
from datetime import datetime, timezone
import logging
from ares.domain.tools import ToolSpec, ToolContext, ToolResult

logger = logging.getLogger(__name__)

class WikimediaTool:
    def __init__(self, user_agent: str = "ARES-V3-Bot (https://example.com)"):
        self.user_agent = user_agent
        self.endpoint = "https://en.wikipedia.org/w/api.php"

    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name="wikimedia_lookup",
            version="1.0",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5, "maximum": 10}
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
                                "pageid": {"type": "integer"},
                                "revid": {"type": "integer"},
                                "snippet": {"type": "string"},
                                "timestamp": {"type": "string"}
                            }
                        }
                    }
                }
            },
            allowed_modes=["research", "comparison"],
            allowed_roles=["workspace_member"],
            billing_class="public_free",
            network_target_policy="strict_allowlist",
            timeout_seconds=10.0,
            byte_limit=1024 * 512,  # 512 KB
            result_limit=10,
            idempotent=True,
            evidence_publication_policy="public_domain_attribution"
        )

    def execute(self, context: ToolContext, inputs: dict) -> ToolResult:
        query = inputs["query"]
        limit = inputs.get("limit", 5)
        
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "utf8": "",
            "format": "json"
        }
        
        headers = {"User-Agent": self.user_agent}
        
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(self.endpoint, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
            
            search_results = data.get("query", {}).get("search", [])
            results = []
            
            for r in search_results:
                results.append({
                    "title": r.get("title"),
                    "pageid": r.get("pageid"),
                    "revid": r.get("revid", 0),
                    "snippet": r.get("snippet", ""),
                    "timestamp": r.get("timestamp", "")
                })
                
            return ToolResult(
                payload={"results": results},
                retrieval_timestamp=datetime.now(timezone.utc),
                capture_timestamp=datetime.now(timezone.utc),
                license="CC BY-SA 3.0",
                attribution="Wikipedia contributors",
                warnings=["Wikimedia is not authoritative for all domains."]
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                return ToolResult(error_category="rate_limited", error_message="Wikimedia rate limited.")
            return ToolResult(error_category="unavailable", error_message=str(e))
        except Exception as e:
            logger.exception("Wikimedia query failed")
            return ToolResult(error_category="unavailable", error_message="Wikimedia query failed.")
