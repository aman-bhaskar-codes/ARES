from collections import Counter
import warnings
from pathlib import Path

from fastapi.routing import APIRoute

from ares.api.app import create_app
from ares.api.settings import Settings


def test_routes_and_openapi_operations_have_single_owner(tmp_path):
    app = create_app(Settings(_env_file=None, database_url=f'sqlite+pysqlite:///{tmp_path / "routes.db"}'))
    import ares.api.app as factory
    routes = [r for module in vars(factory).values() if hasattr(module, "router")
              for r in module.router.routes if isinstance(r, APIRoute)]
    identities = [(method, r.path) for r in routes for method in r.methods]
    assert all(count == 1 for count in Counter(identities).values())
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message="Duplicate Operation ID")
        schema = app.openapi()
    ids = [operation['operationId'] for path in schema['paths'].values()
           for operation in path.values() if isinstance(operation, dict) and 'operationId' in operation]
    assert len(ids) == len(set(ids))
    assert {"get", "post"} <= schema["paths"]["/api/v2/assets"].keys()
    assert len(Path('backend/src/ares/api/app.py').read_text().splitlines()) < 150
