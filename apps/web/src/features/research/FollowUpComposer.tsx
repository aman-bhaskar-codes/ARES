import { ComponentProps } from 'react'
import { Composer } from './Composer'

export function FollowUpComposer(props: ComponentProps<typeof Composer>) {
  return (
    <div className="followup-wrapper" style={{ 
      position: 'sticky', 
      bottom: 'calc(8px + env(safe-area-inset-bottom))', 
      zIndex: 10,
      background: 'var(--surface-sunken)',
      borderRadius: '12px',
      boxShadow: '0 -4px 24px rgba(0,0,0,0.2)',
      border: '1px solid var(--line)',
      padding: '8px',
      marginTop: '40px'
    }}>
      <Composer 
        {...props} 
        placeholder="Ask a follow-up about this research…" 
      />
    </div>
  )
}
