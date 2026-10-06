import { AuthBoundary } from '../features/auth/AuthBoundary'
import { WorkspaceShell } from '../features/workspace/WorkspaceShell'

export default function App() {
  return (
    <AuthBoundary>
      {(authData) => <WorkspaceShell authData={authData} />}
    </AuthBoundary>
  )
}
