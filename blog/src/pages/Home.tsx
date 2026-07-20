import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { usePosts, fmtPattern, fmtPrice } from '@/hooks/usePosts'
import type { Post } from '@/types/post'

function DirectionBadge({ direction }: { direction: string | null }) {
  if (!direction) return null
  const up = direction === 'up'
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        up ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' : 'bg-red-50 text-red-700 ring-1 ring-red-200'
      }`}
    >
      {up ? '▲ up' : '▼ down'}
    </span>
  )
}

function nearestTarget(post: Post): { price: number; pct: number } | null {
  const targets = post.report.preferred?.targets ?? []
  const withPct = targets.filter((t) => t.pct_from_last !== undefined)
  if (!withPct.length) return null
  const t = withPct.reduce((a, b) =>
    Math.abs(a.pct_from_last!) < Math.abs(b.pct_from_last!) ? a : b)
  return { price: t.price, pct: t.pct_from_last! }
}

function PostCard({ post }: { post: Post }) {
  const tgt = nearestTarget(post)
  return (
    <Link
      to={`/post/${post.id}`}
      className="group block rounded-xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <span className="text-xl font-bold tracking-tight text-slate-900">{post.ticker}</span>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">{post.period}</span>
          {post.last_close != null && (
            <span className="font-mono text-sm text-slate-400">@ {fmtPrice(post.last_close)}</span>
          )}
        </div>
        <time className="text-xs text-slate-400">{post.run_date}</time>
      </div>

      {post.no_clean_count ? (
        <p className="mt-3 text-sm font-medium text-slate-500">
          No clean count
          <span className="ml-2 font-mono text-xs text-slate-400">
            best {post.best_score?.toFixed(2) ?? '—'}
          </span>
        </p>
      ) : (
        <>
          <p className="mt-3 text-sm text-slate-800">
            <span className="font-semibold capitalize">{fmtPattern(post.pattern)}</span>{' '}
            <DirectionBadge direction={post.direction} />
            {tgt && (
              <span
                className={`ml-2 font-mono text-xs ${tgt.pct >= 0 ? 'text-emerald-600' : 'text-red-600'}`}
              >
                tgt {fmtPrice(tgt.price)} ({tgt.pct >= 0 ? '+' : ''}{tgt.pct.toFixed(1)}%)
              </span>
            )}
          </p>
          <p className="mt-1.5 line-clamp-2 text-sm leading-relaxed text-slate-500">{post.position_en}</p>
          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-slate-400">
            <span>strength {post.structure_strength?.toFixed(2)}</span>
            <span>confidence {post.relative_confidence?.toFixed(2)}</span>
            <span>{post.monowaves} monowaves</span>
            {post.warnings.length > 0 && (
              <span className="rounded bg-amber-50 px-1.5 py-0.5 font-sans font-medium text-amber-700">
                {post.warnings.length} caveat{post.warnings.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
        </>
      )}
      <p className="mt-3 text-xs text-slate-300 group-hover:text-slate-400">
        {post.window[0]} → {post.window[1]}
        {post.data_through && post.data_through < post.run_date && (
          <span className="ml-2 text-amber-500">data through {post.data_through}</span>
        )}
      </p>
    </Link>
  )
}

export default function Home() {
  const { posts, error } = usePosts()
  const [ticker, setTicker] = useState<string | null>(null)

  const tickers = useMemo(
    () => [...new Set((posts ?? []).map((p) => p.ticker))].sort(),
    [posts],
  )
  const visible = useMemo(
    () => (posts ?? []).filter((p) => !ticker || p.ticker === ticker),
    [posts, ticker],
  )
  const nCounts = (posts ?? []).filter((p) => !p.no_clean_count).length

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-3xl px-6 py-10">
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Wave Log</h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-500">
            Elliott Wave analyses produced by the engine — every run, every symbol, posted as an entry.
            A count without an invalidation level is astrology; "no clean count" is an answer too.
          </p>
          {posts && (
            <p className="mt-3 font-mono text-xs text-slate-400">
              {posts.length} analyses · {nCounts} counts · {posts.length - nCounts} refusals · {tickers.length} symbols
            </p>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-8">
        {tickers.length > 1 && (
          <div className="mb-6 flex flex-wrap gap-2">
            <button
              onClick={() => setTicker(null)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                ticker === null ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:ring-slate-300'
              }`}
            >
              All
            </button>
            {tickers.map((t) => (
              <button
                key={t}
                onClick={() => setTicker(t === ticker ? null : t)}
                className={`rounded-full px-3 py-1 font-mono text-xs font-medium transition ${
                  ticker === t ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:ring-slate-300'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        )}

        {error && <p className="text-sm text-red-600">Failed to load posts: {error}</p>}
        {!posts && !error && <p className="text-sm text-slate-400">Loading…</p>}
        <div className="grid gap-4">
          {visible.map((p) => <PostCard key={p.id} post={p} />)}
        </div>
        {posts && (
          <footer className="mt-10 border-t border-slate-200 pt-6 text-xs text-slate-400">
            generated from the engine's structured reports · Elliott Wave engine v1.1
          </footer>
        )}
      </main>
    </div>
  )
}
