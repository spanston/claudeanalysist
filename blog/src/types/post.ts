export interface Invalidation {
  price: number
  degree: number
  rule: string
  label: string
  binding?: boolean
}

export interface Target {
  price: number
  basis: string
  degree: number
  label: string
}

export interface Report {
  meta: {
    ticker: string
    run_date: string
    window: string[]
    monowaves: number
    pivot_k: number
  }
  no_clean_count: boolean
  best_score?: number | null
  message?: string
  anchor?: { date: string; index: number }
  preferred?: {
    pattern: string
    structure_strength: number
    relative_confidence: number
    direction: string
    span: string[]
    position: { path: string[]; text_en: string; text_sv: string }
    invalidations: Invalidation[]
    targets: Target[]
  }
  alternate?: {
    anchor_date: string
    pattern: string
    score: number
    direction: string
    span: string[]
    same_anchor?: boolean
  } | null
  anchors_considered: { date: string; score: number | null }[]
}

export interface Post {
  id: string
  ticker: string
  period: string
  run_date: string
  window: string[]
  monowaves: number
  no_clean_count: boolean
  pattern: string | null
  direction: string | null
  structure_strength: number | null
  relative_confidence: number | null
  position_en: string | null
  best_score?: number | null
  svg: string | null
  report: Report
}

export interface Manifest {
  posts: Post[]
}
