export interface Invalidation {
  price: number
  degree: number
  rule: string
  label: string
  binding?: boolean
  pct_from_last?: number
}

export interface Target {
  price: number
  basis: string
  degree: number
  label: string
  pct_from_last?: number
}

export interface Report {
  meta: {
    ticker: string
    run_date: string
    window: string[]
    monowaves: number
    pivot_k: number
    last_close?: number | null
    data_through?: string | null
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
  warnings?: string[]
}

export interface Post {
  id: string
  ticker: string
  period: string
  run_date: string
  window: string[]
  monowaves: number
  last_close: number | null
  data_through: string | null
  no_clean_count: boolean
  pattern: string | null
  direction: string | null
  structure_strength: number | null
  relative_confidence: number | null
  position_en: string | null
  best_score?: number | null
  warnings: string[]
  svg: string | null
  report: Report
}

export interface Manifest {
  posts: Post[]
}
