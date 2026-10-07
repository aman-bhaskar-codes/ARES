import { ComponentProps } from 'react'
import { Composer } from './Composer'

export function FollowUpComposer(props: ComponentProps<typeof Composer>) {
  return <Composer {...props} placeholder="Ask a follow-up about this research…" />
}
