import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Search } from 'lucide-react'
import { countryLabel } from '../country'

interface Option {
  value: string
  label: string
}

interface Props {
  /** Current stored value — the original country code/name (not the label). */
  value: string
  options: Option[]
  onChange: (value: string) => void
  required?: boolean
  placeholder?: string
}

/**
 * Type-ahead country selector. The user types to filter the list by country
 * name or code; selecting an option stores its original `value` (code/name) so
 * submission/storage stay unchanged. Free text is allowed for countries not in
 * the list.
 */
export default function CountryCombobox({
  value, options, onChange, required, placeholder = 'Search country…',
}: Props) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const wrapRef = useRef<HTMLDivElement>(null)

  // Display label for the currently stored value (name if known, else raw value).
  const displayValue = value ? countryLabel(value) : ''

  // When closed, the input mirrors the selected value's label. While open the
  // input holds the live search query.
  const inputText = open ? query : displayValue

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter(
      (o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q),
    )
  }, [query, options])

  // Close on outside click.
  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const openDropdown = () => {
    setQuery('')
    setHighlight(0)
    setOpen(true)
  }

  const select = (opt: Option) => {
    onChange(opt.value)
    setOpen(false)
    setQuery('')
  }

  // On blur, if the typed text exactly matches a known option (by label or
  // code), commit that option's original value so we store the code rather
  // than the typed label. Otherwise the free text is kept as-is.
  const handleBlur = () => {
    if (!open && !query) return
    const q = query.trim().toLowerCase()
    if (!q) return
    const exact = options.find(
      (o) => o.label.toLowerCase() === q || o.value.toLowerCase() === q,
    )
    if (exact) onChange(exact.value)
  }

  const handleInput = (text: string) => {
    setQuery(text)
    setHighlight(0)
    if (!open) setOpen(true)
    // Treat typed text as a free-text value too, so unmatched countries are
    // still captured even without selecting an option.
    onChange(text)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open && (e.key === 'ArrowDown' || e.key === 'Enter')) {
      openDropdown()
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlight((h) => Math.min(h + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight((h) => Math.max(h - 1, 0))
    } else if (e.key === 'Enter') {
      if (filtered[highlight]) {
        e.preventDefault()
        select(filtered[highlight])
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div ref={wrapRef} className="nf-combobox" style={{ position: 'relative', flex: 1 }}>
      <div style={{ position: 'relative' }}>
        <Search
          size={14}
          style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', opacity: 0.5, pointerEvents: 'none' }}
        />
        <input
          value={inputText}
          onChange={(e) => handleInput(e.target.value)}
          onFocus={openDropdown}
          onBlur={handleBlur}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          required={required}
          autoComplete="off"
          style={{ width: '100%', paddingLeft: 30, paddingRight: 28 }}
        />
        <ChevronDown
          size={16}
          onClick={() => (open ? setOpen(false) : openDropdown())}
          style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', opacity: 0.6, cursor: 'pointer' }}
        />
      </div>

      {open && (
        <ul className="nf-combobox-list" role="listbox">
          {filtered.length === 0 ? (
            <li className="nf-combobox-empty">No match — press to use “{query}” as entered</li>
          ) : (
            filtered.map((opt, i) => (
              <li
                key={opt.value}
                role="option"
                aria-selected={i === highlight}
                className={`nf-combobox-option ${i === highlight ? 'active' : ''} ${opt.value === value ? 'selected' : ''}`}
                onMouseEnter={() => setHighlight(i)}
                onMouseDown={(e) => { e.preventDefault(); select(opt) }}
              >
                <span>{opt.label}</span>
                <span className="nf-combobox-code">{opt.value}</span>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}
