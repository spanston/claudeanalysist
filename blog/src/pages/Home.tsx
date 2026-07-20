import { Link } from 'react-router'
import { usePosts, fmtPattern } from '@/hooks/usePosts'
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

function PostCard({ post }: { post: Post }) {
  return (
    <Link
      to={`/post/${post.id}`}
      className="group block rounded-xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <span className="text-xl font-bold tracking-tight text-slate-900">{post.ticker}</span>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">{post.period}</span>
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
          </p>
          <p className="mt-1.5 line-clamp-2 text-sm leading-relaxed text-slate-500">{post.position_en}</p>
          <div className="mt-4 flex gap-4 font-mono text-xs text-slate-400">
            <span>strength {post.structure_strength?.toFixed(2)}</span>
            <span>confidence {post.relative_confidence?.toFixed(2)}</span>
            <span>{post.monowaves} monowaves</span>
          </div>
        </>
      )}
      <p className="mt-3 text-xs text-slate-300 group-hover:text-slate-400">
        {post.window[0]} → {post.window[1]}
      </p>
    </Link>
  )
}

export default function Home() {
  const { posts, error } = usePosts()

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-3xl px-6 py-10">
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Wave Log</h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-500">
            Elliott Wave analyses produced by the engine — every run, every symbol, posted as an entry.
            A count without an invalidation level is astrology; "no clean count" is an answer too.
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-8">
        {error && <p className="text-sm text-red-600">Failed to load posts: {error}</p>}
        {!posts && !error && <p className="text-sm text-slate-400">Loading…</p>}
        <div className="grid gap-4">
          {posts?.map((p) => <PostCard key={p.id} post={p} />)}
        </div>
        {posts && (
          <footer className="mt-10 border-t border-slate-200 pt-6 text-xs text-slate-400">
            {posts.length} analyses · generated from the engine's structured reports
          </footer>
        )}
      </main>
    </div>
  )
}
