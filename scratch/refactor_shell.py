import re

with open('apps/web/src/features/workspace/WorkspaceShell.tsx', 'r') as f:
    content = f.read()

# Fix imports
# replace ../lib/ with ../../lib/
content = content.replace('../lib/', '../../lib/')
# replace ../features/ with ../
content = content.replace('../features/', '../')

# Fix component signature
content = content.replace('export default function App() {', 'export function WorkspaceShell({ authData }: { authData: import(\'../../lib/api/types\').Principal }) {')

# Remove auth logic
content = re.sub(r'^\s*const auth = useQuery\(\{ queryKey: \[\'auth-me\'\].*\n', '', content, flags=re.MULTILINE)
content = re.sub(r'^\s*const authenticated = Boolean\(auth\.data\)\n', '  const authenticated = true\n', content, flags=re.MULTILINE)

# We can replace all `auth.data` with `authData`
# Wait, auth.data might have optional chaining `auth.data?.role` -> `authData.role`
content = content.replace('auth.data?.', 'authData.')
content = content.replace('auth.data.', 'authData.')
content = content.replace('!auth.data', '!authData')

# Remove the auth boundary renders
# auth.isPending
content = re.sub(r'^\s*if \(auth\.isPending\) \{[\s\S]*?^\s*\}\n', '', content, flags=re.MULTILINE)
# sessionExpired
content = re.sub(r'^\s*if \(sessionExpired \|\| \(auth\.error instanceof ApiError && auth\.error\.status === 401\)\) \{[\s\S]*?^\s*\}\n', '', content, flags=re.MULTILINE)
# auth.isError
content = re.sub(r'^\s*if \(auth\.isError \|\| !authData\) \{[\s\S]*?^\s*\}\n', '', content, flags=re.MULTILINE)

# Remove sessionExpired hooks
content = re.sub(r'^\s*const \[sessionExpired, setSessionExpired\] = useState\(false\)\n', '', content, flags=re.MULTILINE)
content = re.sub(r'^\s*useEffect\(\(\) => \{\n\s*const expire = \(\) => setSessionExpired\(true\)\n\s*window\.addEventListener\(\'ares:auth-expired\', expire\)\n\s*return \(\) => window\.removeEventListener\(\'ares:auth-expired\', expire\)\n\s*\}, \[\]\)\n', '', content, flags=re.MULTILINE)

with open('apps/web/src/features/workspace/WorkspaceShell.tsx', 'w') as f:
    f.write(content)
