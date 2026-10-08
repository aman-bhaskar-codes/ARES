import { MessageSquarePlus } from 'lucide-react'

export function RelatedQuestions({ questions, onAsk }: { questions: string[]; onAsk: (q: string) => void }) {
  if (!questions || questions.length === 0) return null

  return (
    <section className="gap-card" style={{ marginTop: '12px' }}>
      <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
        <MessageSquarePlus size={18} style={{ marginTop: '2px', color: 'var(--brand)' }} />
        <div className="gap-content">
          <strong>Related questions</strong>
          <div className="related-questions-list" style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {questions.map((q, idx) => (
              <button 
                key={idx} 
                className="quiet-button" 
                style={{ 
                  textAlign: 'left', 
                  padding: '8px 12px', 
                  background: 'var(--bg)', 
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  whiteSpace: 'normal',
                  height: 'auto',
                  lineHeight: '1.4'
                }}
                onClick={() => onAsk(q)}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
