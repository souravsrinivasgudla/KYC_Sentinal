import { KYCResult } from '../api'

export interface EvidenceCheck {
  id: string
  label: string
  satisfied: boolean
  detail?: string
  category: 'validation' | 'identity' | 'document' | 'profile_match'
}

export interface EvidenceDocDetail {
  evidenceId: string
  filename: string
  docType: string
  docTypeDisplay: string
  verdict: string
  verdictReason?: string
  docNumber?: string
  completeness: number
  trustSignal: number
  validityConfidence: number
  poi: boolean
  poa: boolean
  satisfiedChecks: string[]
  unsatisfiedChecks: string[]
  validityIssues: string[]
  groqNotes?: string
  groqIntegrityScore?: number
  extractedFields: Record<string, string | boolean | number>
  profileMatch?: {
    nameMatches?: boolean
    dobMatches?: boolean
    nameSimilarity?: number
    mismatchDetails: string[]
  }
}

export interface EvidenceSummary {
  hasEvidence: boolean
  summary?: string
  overallConfidence?: number
  recommendation?: string
  validationPassed: boolean
  mlPassed: boolean
  groqPassed: boolean
  checks: EvidenceCheck[]
  criticalIssues: string[]
  documentsReviewed: Array<{
    filename: string
    docType: string
    matchesProfile: boolean
    idNumberMatches: boolean
    authenticityScore: number
    issues: string[]
  }>
  documents: EvidenceDocDetail[]
  stats: {
    totalDocs: number
    verified: number
    rejected: number
    review: number
    hasPoi: boolean
    hasPoa: boolean
  }
}

function boolCheck(
  id: string,
  label: string,
  value: boolean | undefined,
  category: EvidenceCheck['category'],
  detail?: string,
  defaultWhenMissing = false,
): EvidenceCheck {
  const satisfied = value ?? defaultWhenMissing
  return { id, label, satisfied, detail, category }
}

export function buildEvidenceSummary(result: KYCResult): EvidenceSummary {
  const ev = result.evidence_validation ?? {}
  const dv = result.document_verdict
  const uploaded = result.uploaded_evidence ?? []
  const ml = ev.ml_classification ?? {
    has_poi: false,
    has_poa: false,
    per_document: [] as NonNullable<typeof ev.ml_classification>['per_document'],
    any_valid: false,
  }

  const hasPoi = dv?.has_poi ?? ev.has_proof_of_identity ?? ml.has_poi ?? false
  const hasPoa = dv?.has_poa ?? ev.has_proof_of_address ?? ml.has_poa ?? false

  const dvPerDoc = dv?.per_document ?? []
  const mlPerDoc = ml.per_document ?? []
  const perDoc: Record<string, unknown>[] = dvPerDoc.length > 0
    ? dvPerDoc.map((d) => d as unknown as Record<string, unknown>)
    : mlPerDoc.map((d) => d as unknown as Record<string, unknown>)

  const verified = dv?.verified_count ?? perDoc.filter((d) => d.verdict === 'VERIFIED' || d.is_valid === true).length
  const rejected = dv?.rejected_count ?? perDoc.filter((d) => d.verdict === 'REJECTED').length
  const review = dv?.review_count ?? perDoc.filter((d) => d.verdict === 'NEEDS_REVIEW').length

  const checks: EvidenceCheck[] = [
    boolCheck('combined', 'Combined evidence validation', ev.validation_passed, 'validation',
      'ML document checks and Groq semantic validation both passed'),
    boolCheck('ml', 'ML document validation', ev.ml_validation_passed ?? ml.any_valid, 'validation',
      'XGBoost / Indian document verification pipeline'),
    boolCheck('groq', 'Groq semantic validation', ev.groq_validation_passed, 'validation',
      'Groq cross-check of document content against profile'),
    boolCheck('identity', 'Identity verified', ev.identity_verified, 'identity'),
    boolCheck('poi', 'Proof of identity (POI)', hasPoi, 'identity',
      'Valid identity document detected (Aadhaar, PAN, Passport, etc.)'),
    boolCheck('poa', 'Proof of address (POA)', hasPoa, 'identity',
      'Valid address document detected'),
    boolCheck('pof', 'Proof of funds verified', ev.proof_of_funds_verified, 'identity'),
    boolCheck('id_match', 'ID number matches declared', ev.id_number_matches_declared, 'profile_match',
      'Declared ID matches number on uploaded document'),
    boolCheck('proof_identity', 'Groq proof of identity', ev.proof_of_identity, 'identity'),
    boolCheck('uploaded', 'Documents uploaded', uploaded.length > 0, 'document',
      uploaded.length > 0 ? `${uploaded.length} file(s) on record` : 'No documents uploaded'),
  ]

  const documentsReviewed = (ev.documents_reviewed as Array<Record<string, unknown>> | undefined ?? []).map((d) => ({
    filename: String(d.filename ?? 'Unknown'),
    docType: String(d.doc_type ?? 'other'),
    matchesProfile: Boolean(d.matches_profile),
    idNumberMatches: Boolean(d.id_number_matches),
    authenticityScore: Number(d.authenticity_score ?? 0),
    issues: Array.isArray(d.issues) ? d.issues.filter((i): i is string => typeof i === 'string') : [],
  }))

  const documents: EvidenceDocDetail[] = perDoc.map((doc) => {
    const verdict = String(doc.verdict ?? ((doc.is_valid as boolean) ? 'VERIFIED' : 'NEEDS_REVIEW'))
    const kycPurpose = (doc.kyc_purpose as { poi?: boolean; poa?: boolean }) ?? {}
    const profileMatch = doc.groq_profile_match as EvidenceDocDetail['profileMatch'] | undefined
    const mismatchDetails = profileMatch?.mismatchDetails
      ?? (profileMatch as { mismatch_details?: string[] })?.mismatch_details
      ?? []
    const validityIssues = Array.isArray(doc.validity_issues)
      ? doc.validity_issues.filter((i): i is string => typeof i === 'string')
      : []

    const satisfiedChecks: string[] = []
    const unsatisfiedChecks: string[] = []

    if (verdict === 'VERIFIED') satisfiedChecks.push('Document verdict: VERIFIED')
    else unsatisfiedChecks.push(`Document verdict: ${verdict}`)

    if (kycPurpose.poi) satisfiedChecks.push('Qualifies as Proof of Identity')
    else unsatisfiedChecks.push('Does not qualify as POI')

    if (kycPurpose.poa) satisfiedChecks.push('Qualifies as Proof of Address')
    else unsatisfiedChecks.push('Does not qualify as POA')

    if (profileMatch?.nameMatches) satisfiedChecks.push('Name matches profile')
    else if (profileMatch && profileMatch.nameMatches === false) unsatisfiedChecks.push('Name does not match profile')

    if (profileMatch?.dobMatches) satisfiedChecks.push('Date of birth matches profile')
    else if (profileMatch && profileMatch.dobMatches === false) unsatisfiedChecks.push('DOB does not match profile')

    if (doc.doc_number) {
      satisfiedChecks.push(`Document number: ${doc.doc_number}`)
    }
    const dlFromLabel = doc.dl_number_from_label as string | undefined
    if (dlFromLabel && dlFromLabel !== doc.doc_number) {
      satisfiedChecks.push(`DL No on document: ${dlFromLabel}`)
    }
    const idMismatch = doc.id_mismatch_detail as { declared?: string; extracted?: string } | undefined
    if (idMismatch?.declared) {
      unsatisfiedChecks.push(
        `ID mismatch — entered ${idMismatch.declared}, document shows ${idMismatch.extracted ?? 'unknown'}`,
      )
    } else if (doc.id_mismatch) {
      unsatisfiedChecks.push('Entered ID does not match DL No on document')
    }
    const nameMismatch = doc.name_mismatch_detail as { declared?: string; extracted?: string } | undefined
    if (nameMismatch?.declared) {
      unsatisfiedChecks.push(
        `Name mismatch — entered ${nameMismatch.declared}, document shows ${nameMismatch.extracted ?? 'unknown'}`,
      )
    } else if (doc.name_mismatch) {
      unsatisfiedChecks.push('Entered name does not match name on driving licence')
    }
    const nameOnDoc = doc.name_from_document as string | undefined
    if (nameOnDoc && !nameMismatch && !doc.name_mismatch) {
      satisfiedChecks.push(`Name on document: ${nameOnDoc}`)
    }

    const groqReview = documentsReviewed.find((r) => r.filename === doc.filename)
    if (groqReview?.matchesProfile) satisfiedChecks.push('Groq: matches customer profile')
    else if (groqReview && !groqReview.matchesProfile) unsatisfiedChecks.push('Groq: does not match customer profile')

    if (groqReview?.idNumberMatches) satisfiedChecks.push('Groq: ID number matches')
    else if (groqReview && !groqReview.idNumberMatches) unsatisfiedChecks.push('Groq: ID number mismatch')

    if ((doc.completeness_score as number) >= 0.7) {
      satisfiedChecks.push(`Completeness ${Math.round((doc.completeness_score as number) * 100)}%`)
    } else {
      unsatisfiedChecks.push(`Low completeness ${Math.round(((doc.completeness_score as number) ?? 0) * 100)}%`)
    }

    if ((doc.trust_signal_score as number) >= 0.7) {
      satisfiedChecks.push(`Trust signal ${Math.round((doc.trust_signal_score as number) * 100)}%`)
    } else {
      unsatisfiedChecks.push(`Low trust signal ${Math.round(((doc.trust_signal_score as number) ?? 0) * 100)}%`)
    }

    mismatchDetails.forEach((m) => unsatisfiedChecks.push(m))
    validityIssues.forEach((issue) => unsatisfiedChecks.push(issue))

    return {
      evidenceId: String(doc.evidence_id ?? ''),
      filename: String(doc.filename ?? 'Unknown'),
      docType: String(doc.doc_type ?? ''),
      docTypeDisplay: String(doc.doc_type_display ?? doc.doc_type ?? 'Document'),
      verdict,
      verdictReason: String(doc.verdict_reason ?? ''),
      docNumber: String(doc.doc_number ?? ''),
      completeness: Number(doc.completeness_score ?? 0),
      trustSignal: Number(doc.trust_signal_score ?? 0),
      validityConfidence: Number(doc.validity_confidence ?? 0),
      poi: Boolean(kycPurpose.poi),
      poa: Boolean(kycPurpose.poa),
      satisfiedChecks,
      unsatisfiedChecks,
      validityIssues,
      groqNotes: String(doc.groq_notes ?? ''),
      groqIntegrityScore: doc.groq_integrity_score as number | undefined,
      extractedFields: (doc.groq_extracted_fields as Record<string, string | boolean | number>) ?? {},
      profileMatch: profileMatch
        ? { ...profileMatch, mismatchDetails }
        : undefined,
    }
  })

  // Uploaded files without per-document analysis
  uploaded.forEach((u) => {
    if (!documents.some((d) => d.evidenceId === u.evidence_id || d.filename === u.original_filename)) {
      documents.push({
        evidenceId: u.evidence_id,
        filename: u.original_filename,
        docType: 'unknown',
        docTypeDisplay: 'Uploaded file',
        verdict: 'PENDING',
        completeness: 0,
        trustSignal: 0,
        validityConfidence: 0,
        poi: false,
        poa: false,
        satisfiedChecks: ['File uploaded'],
        unsatisfiedChecks: ['No automated analysis available'],
        validityIssues: [],
        extractedFields: {},
      })
    }
  })

  const criticalIssues = [
    ...(Array.isArray(ev.critical_issues) ? ev.critical_issues.filter((i): i is string => typeof i === 'string') : []),
    ...(dv?.rejection_reasons ?? []),
  ].filter((v, i, a) => a.indexOf(v) === i)

  return {
    hasEvidence: uploaded.length > 0 || documents.length > 0 || Boolean(ev.summary),
    summary: ev.summary,
    overallConfidence: ev.overall_confidence,
    recommendation: ev.recommendation,
    validationPassed: Boolean(ev.validation_passed),
    mlPassed: Boolean(ev.ml_validation_passed ?? ml.any_valid),
    groqPassed: Boolean(ev.groq_validation_passed),
    checks,
    criticalIssues,
    documentsReviewed,
    documents,
    stats: {
      totalDocs: dv?.total_docs ?? perDoc.length ?? uploaded.length,
      verified,
      rejected,
      review,
      hasPoi,
      hasPoa,
    },
  }
}
