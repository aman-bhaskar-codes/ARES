import { Plus } from 'lucide-react'

export function RelatedQuestions({ questions, onAsk, disabled = false }: { questions: string[]; onAsk: (q: string) => void; disabled?: boolean }) {
  if (!questions?.length) return null
  return <section className="related-questions"><h2>Keep exploring</h2>{questions.map((question) => <button disabled={disabled} key={question} onClick={() => onAsk(question)}><span>{question}</span><Plus size={18} /></button>)}</section>
}
