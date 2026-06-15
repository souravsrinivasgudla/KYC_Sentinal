import { FormEvent, useRef, useState, useEffect, ChangeEvent, useMemo } from 'react'
import { Upload, FileCheck, X, AlertTriangle } from 'lucide-react'
import { CustomCustomer } from '../api'
import { toNationalityOptions } from '../nationality'
import NationalityCombobox from './NationalityCombobox'

interface Props {
  form: CustomCustomer
  countries: string[]
  occupations: string[]
  documents: File[]
  onChange: (form: CustomCustomer) => void
  onDocumentsChange: (files: File[]) => void
  onSubmit: () => void
  loading: boolean
}

const OPTIONAL: (keyof CustomCustomer)[] = ['source_of_funds', 'id_number']
const ACCEPT = '.pdf,.txt,.jpg,.jpeg,.png,.webp'
const STANDARD_FUNDS = ["Salary", "Business Revenue", "Savings", "Investments", "Inheritance", "Gifts"]

export default function CustomKYCForm({
  form, countries, occupations, documents, onChange, onDocumentsChange, onSubmit, loading,
}: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  const set = (field: keyof CustomCustomer, value: string) => onChange({ ...form, [field]: value })

  const [occupationSelect, setOccupationSelect] = useState('')
  const [fundsSelect, setFundsSelect] = useState('')

  // Map backend country codes/names to user-friendly nationality labels for
  // display. The option value stays the original code so submission/storage
  // are unaffected.
  const nationalityOptions = useMemo(() => toNationalityOptions(countries), [countries])

  useEffect(() => {
    if (!form.occupation) {
      setOccupationSelect('')
    } else if (occupationSelect !== 'Other') {
      setOccupationSelect(occupations.includes(form.occupation) ? form.occupation : 'Other')
    }
  }, [form.occupation, occupations])

  useEffect(() => {
    if (!form.source_of_funds) {
      setFundsSelect('')
    } else if (fundsSelect !== 'Other') {
      setFundsSelect(STANDARD_FUNDS.includes(form.source_of_funds) ? form.source_of_funds : 'Other')
    }
  }, [form.source_of_funds])

  const handleOccupationChange = (e: ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value
    setOccupationSelect(val)
    if (val === 'Other') {
      set('occupation', '')
    } else {
      set('occupation', val)
    }
  }

  const handleFundsChange = (e: ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value
    setFundsSelect(val)
    if (val === 'Other') {
      set('source_of_funds', '')
    } else {
      set('source_of_funds', val)
    }
  }

  const handleFiles = (files: FileList | null) => {
    if (!files) return
    onDocumentsChange([...documents, ...Array.from(files)])
  }

  const removeDoc = (idx: number) => onDocumentsChange(documents.filter((_, i) => i !== idx))

  const missingOptional = OPTIONAL.filter((f) => !form[f]?.trim())

  return (
    <form className="nf-form" onSubmit={(e: FormEvent) => { e.preventDefault(); onSubmit() }}>
      <div className="nf-form-grid">
        <div className="nf-field">
          <label>Full Name *</label>
          <input value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="Legal full name" required />
        </div>
        <div className="nf-field">
          <label>Date of Birth *</label>
          <input type="date" value={form.dob} onChange={(e) => set('dob', e.target.value)} required />
        </div>
        <div className="nf-field">
          <label>Nationality *</label>
          <NationalityCombobox
            value={form.nationality}
            options={nationalityOptions}
            onChange={(v) => set('nationality', v)}
            required
          />
        </div>
        <div className="nf-field">
          <label>Occupation *</label>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <select
              value={occupationSelect}
              onChange={handleOccupationChange}
              required
              style={{ flex: 1 }}
            >
              <option value="" disabled>Select Occupation</option>
              {occupations.map((o) => <option key={o} value={o}>{o}</option>)}
              <option value="Other">Other</option>
            </select>
            {occupationSelect === 'Other' && (
              <input
                value={form.occupation}
                onChange={(e) => set('occupation', e.target.value)}
                placeholder="Enter occupation"
                required
                style={{ flex: 1 }}
              />
            )}
          </div>
        </div>
        <div className={`nf-field ${!form.source_of_funds?.trim() ? 'nf-field-warn' : ''}`}>
          <label>Source of Funds {!form.source_of_funds?.trim() && <span className="nf-warn-tag">Missing</span>}</label>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <select
              value={fundsSelect}
              onChange={handleFundsChange}
              style={{ flex: 1 }}
            >
              <option value="">Select Source of Funds</option>
              {STANDARD_FUNDS.map((f) => <option key={f} value={f}>{f}</option>)}
              <option value="Other">Other</option>
            </select>
            {fundsSelect === 'Other' && (
              <input
                value={form.source_of_funds}
                onChange={(e) => set('source_of_funds', e.target.value)}
                placeholder="Enter source of funds"
                style={{ flex: 1 }}
              />
            )}
          </div>
        </div>
        <div className={`nf-field ${!form.id_number?.trim() ? 'nf-field-warn' : ''}`}>
          <label>ID / DL Number {!form.id_number?.trim() && <span className="nf-warn-tag">Missing</span>}</label>
          <input
            value={form.id_number}
            onChange={(e) => set('id_number', e.target.value)}
            placeholder="DL No. as on licence, PAN, Aadhaar, or Passport"
          />
        </div>
      </div>

      <div className={`nf-upload-zone ${documents.length === 0 ? 'nf-upload-empty' : ''}`}>
        <input ref={fileRef} type="file" accept={ACCEPT} multiple hidden onChange={(e) => handleFiles(e.target.files)} />
        <div className="nf-upload-inner" onClick={() => fileRef.current?.click()}>
          <Upload size={28} />
          <div>
            <strong>Upload Proof Documents</strong>
            <p>ID, passport, proof of funds — PDF, TXT, JPG, PNG</p>
          </div>
        </div>
        {documents.length === 0 && (
          <div className="nf-upload-alert">
            <AlertTriangle size={14} />
            <span>At least one document required for evidence validation</span>
          </div>
        )}
        {documents.length > 0 && (
          <div className="nf-file-list">
            {documents.map((f, i) => (
              <div key={i} className="nf-file-item">
                <FileCheck size={14} />
                <span>{f.name}</span>
                <button type="button" onClick={() => removeDoc(i)}><X size={14} /></button>
              </div>
            ))}
          </div>
        )}
      </div>

      {missingOptional.length > 0 && (
        <div className="nf-notice">
          <AlertTriangle size={14} />
          Optional fields not provided will be flagged during verification.
        </div>
      )}

      <button type="submit" className="nf-btn nf-btn-primary" disabled={loading}>
        {loading ? 'Verifying...' : 'Start KYC Verification'}
      </button>
    </form>
  )
}
