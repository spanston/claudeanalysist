import { Link, useParams } from 'react-router'
import { usePosts, fmtPattern, fmtPrice } from '@/hooks/usePosts'

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-0.5 font-mono text-sm font-semibold text-slate-800">{value}</div>
    </div>
  )
}

export default function PostPage() {
  const { id } = useParams()
  const { posts, error } = usePosts()
  const post = posts?.find((p) => p.id === id)

  if (error) return <p className="p-10 text-sm text-red-600">{error}</p>
  if (!posts) return <p className="p-10 text-sm text-slate-400">Loading…</p>
  if (!post)
    return (
      <p className="p-10 text-sm text-slate-500">
        Post not found. <Link to="/" className="text-blue-600 underline">Back to index</Link>
      </p>
    )

  const r = post.report
  const pref = r.preferred

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-4xl px-6 py-8">
          <Link to="/" className="text-xs text-slate-400 hover:text-slate-600">← Wave Log</Link>
          <div className="mt-3 flex flex-wrap items-baseline gap-3">
            <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">{post.ticker}</h1>
            <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-500">{post.period}</span>
            <time className="text-sm text-slate-400">{post.run_date}</time>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            {post.window[0]} → {post.window[1]} · {post.monowaves} monowaves
            {r.anchor && <> · anchored {r.anchor.date}</>}
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-8">
        {r.no_clean_count ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-6">
            <h2 className="text-lg font-bold text-amber-900">No clean count</h2>
            <p className="mt-1 text-sm text-amber-800">{r.message}</p>
            <p className="mt-2 font-mono text-xs text-amber-700">
              best score {r.best_score?.toFixed(2) ?? '—'} (needs ≥ 3.00 nats of evidence vs a random walk)
            </p>
          </div>
        ) : (
          pref && (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                <Stat label="Pattern" value={fmtPattern(pref.pattern)} />
                <Stat label="Direction" value={pref.direction === 'up' ? '▲ up' : '▼ down'} />
                <Stat label="Structure strength" value={pref.structure_strength.toFixed(2)} />
                <Stat label="Rel. confidence" value={pref.relative_confidence.toFixed(2)} />
                <Stat
                  label="Last close"
                  value={r.meta.last_close != null ? fmtPrice(r.meta.last_close) : '—'}
                />
              </div>

              <section className="mt-6 rounded-xl border border-slate-200 bg-white p-6">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Position</h2>
                <p className="mt-2 text-lg font-medium text-slate-900">{pref.position.text_en}</p>
                <p className="mt-1 text-sm text-slate-500">{pref.position.text_sv}</p>

                {pref.invalidations.length > 0 && (
                  <>
                    <h3 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">
                      Invalidation
                    </h3>
                    <ul className="mt-2 space-y-1.5">
                      {pref.invalidations.map((inv, i) => (
                        <li key={i} className="flex items-baseline gap-2 text-sm">
                          <span className="font-mono font-semibold text-red-700">{fmtPrice(inv.price)}</span>
                          {inv.pct_from_last !== undefined && (
                            <span className="font-mono text-xs text-red-400">
                              ({inv.pct_from_last >= 0 ? '+' : ''}{inv.pct_from_last.toFixed(1)}%)
                            </span>
                          )}
                          <span className="text-slate-600">{inv.rule}</span>
                          <span className="text-xs text-slate-400">
                            ({inv.label}, degree {inv.degree})
                          </span>
                          {inv.binding && (
                            <span className="rounded bg-red-50 px-1.5 text-[11px] font-medium text-red-600">
                              binding
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </>
                )}

                {pref.targets.length > 0 && (
                  <>
                    <h3 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">Targets</h3>
                    <ul className="mt-2 space-y-1.5">
                      {pref.targets.map((t, i) => (
                        <li key={i} className="flex items-baseline gap-2 text-sm">
                          <span className="font-mono font-semibold text-blue-700">{fmtPrice(t.price)}</span>
                          {t.pct_from_last !== undefined && (
                            <span className="font-mono text-xs text-blue-400">
                              ({t.pct_from_last >= 0 ? '+' : ''}{t.pct_from_last.toFixed(1)}%)
                            </span>
                          )}
                          <span className="text-slate-600">{t.basis}</span>
                          <span className="text-xs text-slate-400">({t.label})</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </section>

              {r.alternate && (
                <section className="mt-4 rounded-xl border border-slate-200 bg-white p-6">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
                    Alternate count{r.alternate.same_anchor ? ' · same anchor' : ''}
                  </h2>
                  <p className="mt-2 text-sm text-slate-800">
                    <span className="font-semibold capitalize">{fmtPattern(r.alternate.pattern)}</span>{' '}
                    ({r.alternate.direction}) from {r.alternate.anchor_date} · score{' '}
                    {r.alternate.score.toFixed(2)}
                  </p>
                </section>
              )}
            </>
          )
        )}

        {(r.warnings?.length ?? 0) > 0 && (
          <section className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-amber-700">Caveats</h2>
            <ul className="mt-2 space-y-1.5">
              {r.warnings!.map((w, i) => (
                <li key={i} className="text-sm leading-relaxed text-amber-900">
                  <span className="font-mono font-semibold">{w.split(':')[0]}</span>
                  <span>:{w.split(':').slice(1).join(':')}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {post.svg && (
          <section className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
            <img src={post.svg} alt={`${post.ticker} ${post.period} Elliott Wave chart`} className="w-full" />
          </section>
        )}

        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Anchors considered</h2>
          <div className="mt-2 flex flex-wrap gap-2">
            {r.anchors_considered.map((a, i) => (
              <span key={i} className="rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-600">
                {a.date}: {a.score === null ? 'no root' : a.score.toFixed(2)}
              </span>
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}
