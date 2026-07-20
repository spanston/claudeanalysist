import { useEffect, useState } from 'react'
import type { Manifest, Post } from '@/types/post'

export function usePosts() {
  const [posts, setPosts] = useState<Post[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('posts/manifest.json')
      .then((r) => {
        if (!r.ok) throw new Error(`manifest fetch failed: ${r.status}`)
        return r.json() as Promise<Manifest>
      })
      .then((m) => setPosts(m.posts))
      .catch((e) => setError(String(e)))
  }, [])

  return { posts, error }
}

export function fmtPrice(p: number): string {
  return p >= 1000
    ? p.toLocaleString('en-US', { maximumFractionDigits: 0 })
    : p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function fmtPattern(name: string | null | undefined): string {
  if (!name) return '—'
  return name.replace(/_/g, ' ')
}
