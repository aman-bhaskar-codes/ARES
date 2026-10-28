import { Check, ChevronDown, Cpu, Sparkles } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import type { ModelCatalog, ModelProvider } from '../../lib/api/types'

/** Shared model control for both the home and follow-up composers. */
export function ModelPicker({ value, models, disabled, onChange, onOpen }: {
  value: ModelProvider
  models?: ModelCatalog
  disabled: boolean
  onChange: (value: ModelProvider) => void
  onOpen: () => void
}) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const menuId = useId()
  const selected = models?.models.find(item => item.id === value)
  const Icon = value === 'qwen' ? Cpu : Sparkles
  const close = (restore = false) => { setOpen(false); if (restore) trigger.current?.focus() }
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    const options = menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]:not(:disabled)')
    const current = menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]:not(:disabled)')
    ;(current ?? options?.[0])?.focus()
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  useEffect(() => { if (disabled) setOpen(false) }, [disabled])
  const key = (event: KeyboardEvent) => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); return }
    if (event.key === 'Tab') { close(true); return }
    const options = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]:not(:disabled)') ?? [])
    if (!options.length || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const current = options.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (current + (event.key === 'ArrowUp' ? -1 : 1) + options.length) % options.length
    options[next].focus()
  }
  return <div className="model-picker" ref={root} onKeyDown={key} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setOpen(false) }}>
    <button className="model-picker-trigger" ref={trigger} type="button" disabled={disabled || !models} aria-label={`Answer model: ${selected?.label ?? (value === 'qwen' ? 'Qwen' : 'Gemini')}`} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined}
      onClick={() => { if (!open) onOpen(); setOpen(!open) }} onKeyDown={event => { if (!open && ['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); onOpen(); setOpen(true) } }}>
      <span className="model-mark"><Icon size={16}/></span><span>{selected?.label ?? (value === 'qwen' ? 'Qwen' : 'Gemini')}</span><ChevronDown size={13} className={open ? 'turned' : ''}/>
    </button>
    {open && <div className="model-picker-menu" id={menuId} ref={menu} role="menu" aria-label="Answer model">
      <div className="model-picker-heading"><strong>Answer model</strong><span>Choose your writing model</span></div>
      {models?.models.map(item => {
        const ModelIcon = item.id === 'qwen' ? Cpu : Sparkles
        return <button key={item.id} type="button" role="menuitemradio" aria-checked={value === item.id} disabled={!item.available} className="model-picker-option" onClick={() => { onChange(item.id); close(true) }}>
          <span className="model-mark"><ModelIcon size={19}/></span>
          <span className="model-picker-copy"><strong>{item.label}<small>{item.location === 'local' ? 'Local' : 'Cloud'}</small></strong><span>{!item.available ? 'Not configured' : item.location === 'local' ? 'Runs on your device' : 'Cloud-powered explanations'}</span></span>
          {value === item.id && <Check size={16} className="model-picker-check"/>}
        </button>
      })}
    </div>}
  </div>
}
