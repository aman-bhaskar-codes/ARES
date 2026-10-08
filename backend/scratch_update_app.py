import ast
import os

class EndpointRemover(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if getattr(dec.func.value, 'id', '') == 'app' and dec.func.attr in ('get', 'post', 'put', 'delete', 'patch'):
                    return None
            elif isinstance(dec, ast.Attribute):
                if getattr(dec.value, 'id', '') == 'app' and dec.attr in ('get', 'post', 'put', 'delete', 'patch'):
                    return None
        self.generic_visit(node)
        return node

with open('backend/src/ares/api/app.py') as f:
    source = f.read()

tree = ast.parse(source)
remover = EndpointRemover()
tree = remover.visit(tree)

# Now, we need to add app.include_router(auth.router), etc. inside create_app
# Wait, let's just append them at the end of create_app
# Find create_app
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'create_app':
        # Add the include_router calls right before the return statement.
        # Wait, there is no return statement in create_app in the original file?!
        # Ah, let's check app.py! Wait, let's just append to the body.
        routers = [
            "auth", "system", "conversations", "assets", "ingestions", 
            "segments", "documents", "runs", "evidence", "artifacts", "internal"
        ]
        
        includes = ast.parse("\n".join([f"app.include_router({r}.router)" for r in routers])).body
        
        # Check if there's a return app statement
        if isinstance(node.body[-1], ast.Return):
            node.body = node.body[:-1] + includes + [node.body[-1]]
        else:
            node.body.extend(includes)

# We also need to add the imports for the routers at the top of the file!
imports = ast.parse("\n".join([f"from ares.api.routers import {r}" for r in routers])).body
tree.body = imports + tree.body

with open('backend/src/ares/api/app.py', 'w') as f:
    f.write(ast.unparse(tree))

# Also create backend/src/ares/api/routers/__init__.py
open('backend/src/ares/api/routers/__init__.py', 'w').close()
