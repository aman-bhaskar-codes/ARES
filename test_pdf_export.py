import asyncio
from uuid import uuid4
from ares.application.exports import ExportService
class DummyRun:
    id = uuid4()
    query = "test"
    completed_at = None
    summary_markdown = "test markdown"
class DummyRepo:
    def create_artifact(self, **kwargs):
        pass
class DummyBlobs:
    def put_bytes(self, container, data):
        return "blob_key"

service = ExportService(DummyRepo(), DummyBlobs())
class DummyEvidence:
    pass
try:
    class Req:
        format = "pdf"
    service.create(DummyRun(), Req())
    print("Success")
except Exception as e:
    import traceback
    traceback.print_exc()
