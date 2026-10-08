import ast
import os
import glob
from copy import deepcopy

for path in glob.glob('backend/src/ares/api/routers/*.py'):
    with open(path) as f:
        source = f.read()
    
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Check if 'request' is already an argument
            has_request = any(arg.arg == 'request' for arg in node.args.args)
            if not has_request:
                node.args.kwonlyargs.append(ast.arg(arg='request', annotation=ast.Name(id='Request', ctx=ast.Load())))
                node.args.kw_defaults.append(None)
            
            # Now insert the assignments at the top of the body
            assignments = ast.parse("""
repository = request.app.state.repository
cfg = request.app.state.settings
auth_store = getattr(request.app.state, 'auth_store', None)
oidc = getattr(request.app.state, 'oidc', None)
blobs = request.app.state.blobs
asset_admission = getattr(request.app.state, 'asset_admission', None)
documents = getattr(request.app.state, 'documents', None)
exports = getattr(request.app.state, 'exports', None)
visualizations = getattr(request.app.state, 'visualizations', None)
engine = getattr(request.app.state, 'db_engine', None)
local_media_runtime = getattr(request.app.state, 'local_media_runtime', None)
""").body
            
            node.body = assignments + node.body
    
    with open(path, 'w') as f:
        f.write(ast.unparse(tree))

