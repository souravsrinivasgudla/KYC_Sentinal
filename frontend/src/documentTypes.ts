// KYC document-type metadata shared across the form and display screens.
//
// The selected document type drives:
//   • the dynamic ID-number field label   (idNumberLabel)
//   • the helper text under the field      (idNumberHelper)
// and the raw document number is always sanitised (no spaces) before storage.

// Document types the classifier model is actually trained on (must stay in
// sync with backend doc_classifier.DOC_TYPES). Only these can be verified and
// compared against the uploaded document, so the dropdown lists only these.
export const DOCUMENT_TYPES = [
  'Aadhaar Card',
  'PAN Card',
  'Passport',
  'Voter ID',
  'Driving Licence',
  'Bank Passbook',
] as const

export const OTHER_DOC_TYPE = 'Other'

/** Document types that have a specific ID-number label. Others fall back to "ID Number". */
const ID_LABELS: Record<string, string> = {
  'Aadhaar Card': 'Aadhaar Number',
  'PAN Card': 'PAN Number',
  'Passport': 'Passport Number',
  'Driving Licence': 'Driving Licence Number',
}

/** Helper text shown under the ID-number field for specific document types. */
const ID_HELPERS: Record<string, string> = {
  'Aadhaar Card': 'Enter 12-digit Aadhaar number without spaces.',
  'PAN Card': 'Enter 10-character PAN number.',
  'Passport': 'Enter passport number exactly as shown on the document.',
}

/** Label for the document-number input given the selected document type. */
export function idNumberLabel(docType: string): string {
  return ID_LABELS[docType] || 'ID Number'
}

/** Helper text for the document-number input given the selected document type. */
export function idNumberHelper(docType: string): string {
  return ID_HELPERS[docType] || ''
}

/**
 * Normalise a document number to a consistent, compliance-grade format:
 *   1. remove ALL whitespace (blocks typed spaces, strips pasted spaces,
 *      which also trims leading/trailing whitespace),
 *   2. convert all letters to uppercase.
 *
 *   "ab cd e1234f"       → "ABCDE1234F"
 *   " 1234 5678 9012 "   → "123456789012"
 *   "p1234567"           → "P1234567"
 */
export function sanitizeDocumentNumber(raw: string): string {
  return raw.replace(/\s+/g, '').toUpperCase()
}

/** Per-document-type format rules (validated against the normalised value). */
const FORMAT_RULES: Record<string, { pattern: RegExp; message: string }> = {
  'PAN Card': {
    pattern: /^[A-Z]{5}[0-9]{4}[A-Z]$/,
    message: 'PAN must be 5 letters, 4 digits, then 1 letter (e.g. ABCDE1234F).',
  },
  'Aadhaar Card': {
    pattern: /^\d{12}$/,
    message: 'Aadhaar must be exactly 12 digits.',
  },
  'Passport': {
    pattern: /^[A-Z][0-9]{7}$/,
    message: 'Passport must be 1 letter followed by 7 digits (e.g. P1234567).',
  },
  'Voter ID': {
    pattern: /^[A-Z]{3}[0-9]{7}$/,
    message: 'Voter ID must be 3 letters followed by 7 digits (e.g. ABC1234567).',
  },
}

/**
 * Validate a (normalised) document number against the selected document type.
 * Returns an error message string, or null when valid / no rule applies /
 * the value is empty (the number field itself is optional).
 */
export function validateDocumentNumber(docType: string, value: string): string | null {
  const rule = FORMAT_RULES[docType]
  if (!rule || !value) return null
  return rule.pattern.test(value) ? null : rule.message
}
