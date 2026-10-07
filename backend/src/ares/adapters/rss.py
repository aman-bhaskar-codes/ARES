import httpx
from datetime import datetime, timezone
import logging
import xml.etree.ElementTree as ET
from ares.domain.tools import ToolSpec, ToolContext, ToolResult

logger = logging.getLogger(__name__)

class RSSTool:
    def __init__(self, user_agent: str = "ARES-V3-Bot (https://example.com)"):
        self.user_agent = user_agent

    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name="rss_fetch",
            version="1.0",
            input_schema={
                "type": "object",
                "properties": {
                    "feed_url": {"type": "string", "format": "uri"},
                    "etag": {"type": "string"},
                    "last_modified": {"type": "string"}
                },
                "required": ["feed_url"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "link": {"type": "string"},
                                "published": {"type": "string"},
                                "description": {"type": "string"}
                            }
                        }
                    },
                    "etag": {"type": "string"},
                    "last_modified": {"type": "string"}
                }
            },
            allowed_modes=["watch", "research"],
            allowed_roles=["workspace_member"],
            billing_class="public_free",
            network_target_policy="authorized_sources_only",
            timeout_seconds=10.0,
            byte_limit=1024 * 1024,
            result_limit=100,
            idempotent=True,
            evidence_publication_policy="public_domain_attribution"
        )

    def execute(self, context: ToolContext, inputs: dict) -> ToolResult:
        feed_url = inputs["feed_url"]
        
        headers = {"User-Agent": self.user_agent}
        if "etag" in inputs:
            headers["If-None-Match"] = inputs["etag"]
        if "last_modified" in inputs:
            headers["If-Modified-Since"] = inputs["last_modified"]
            
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(feed_url, headers=headers)
                
            if response.status_code == 304:
                return ToolResult(
                    payload={"entries": [], "etag": inputs.get("etag", ""), "last_modified": inputs.get("last_modified", "")},
                    retrieval_timestamp=datetime.now(timezone.utc),
                    capture_timestamp=datetime.now(timezone.utc),
                )
            
            response.raise_for_status()
            
            # Safe XML parsing (defusedxml is recommended in prod, we'll use basic ET here but avoid external entities)
            parser = ET.XMLParser()
            root = ET.fromstring(response.text, parser=parser)
            
            entries = []
            # Very basic RSS 2.0 / Atom parser stub
            for item in root.findall(".//item")[:100]:
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                pub_date = item.findtext("pubDate", "")
                description = item.findtext("description", "")
                
                entries.append({
                    "title": title,
                    "link": link,
                    "published": pub_date,
                    "description": description
                })
                
            new_etag = response.headers.get("ETag", "")
            new_last_modified = response.headers.get("Last-Modified", "")
            
            return ToolResult(
                payload={"entries": entries, "etag": new_etag, "last_modified": new_last_modified},
                retrieval_timestamp=datetime.now(timezone.utc),
                capture_timestamp=datetime.now(timezone.utc),
                license="Feed owner copyright",
                attribution="RSS Feed"
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(error_category="unavailable", error_message=str(e))
        except ET.ParseError:
            return ToolResult(error_category="unavailable", error_message="Failed to parse XML.")
        except Exception:
            logger.exception("RSS fetch failed")
            return ToolResult(error_category="unavailable", error_message="RSS fetch failed.")
