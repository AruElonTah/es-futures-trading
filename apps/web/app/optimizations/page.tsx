'use client'

import { Suspense, useState } from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { API_BASE } from '@/lib/api'
import type { EquityPoint } from '@/lib/api'
import EquityCurve from '@/components/EquityCurve'

// MUST use ssr:false — plotly.js accesses window at module import time (Pitfall 5 / T-04-03-03)
const Plot = dynamic(() => import('react-plotly.js'), { ssr: false })

// ----------------------------- Types ----------------------------------------

interface OptRun {
  run_id: string
  strategy_id: string
  status: 'running' | 'complete' | 'failed'
  total_combos: number
  completed_combos: number
  fold_count: number
  created_at: string
}

interface OptResult {
  result_id: string
  run_id: string
  fold_idx: number
  param_hash: string
  opening_range_minutes: number
  atr_stop_mult: number
  r_target: number
  is_sharpe: number | null
  oos_sharpe: number | null
  is_return: number | null
  oos_return: number | null
  edge_ratio: number | null
  equity_curve_path: string | null
  created_at: string
}

interface HeatmapData {
  x: number[]
  y: number[]
  z: number[][]
}

// ----------------------------- Axis options ---------------------------------

const AXIS_OPTIONS = [
  'opening_range_minutes',
  'atr_stop_mult',
  'r_target',
] as const

type AxisOption = (typeof AXIS_OPTIONS)[number]

// ----------------------------- Fetch helpers --------------------------------

async function fetchRuns(): Promise<OptRun[]> {
  const res = await fetch(`${API_BASE}/optimizations`)
  if (!res.ok) throw new Error(`GET /optimizations failed: ${res.status}`)
  return res.json()
}

async function fetchResults(runId: string): Promise<OptResult[]> {
  const res = await fetch(`${API_BASE}/optimizations/${runId}/results`)
  if (!res.ok)
    throw new Error(`GET /optimizations/${runId}/results failed: ${res.status}`)
  return res.json()
}

async function fetchHeatmap(
  runId: string,
  axisX: AxisOption,
  axisY: AxisOption
): Promise<HeatmapData> {
  const url = `${API_BASE}/optimizations/${runId}/heatmap?axis_x=${axisX}&axis_y=${axisY}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`GET heatmap failed: ${res.status}`)
  return res.json()
}

async function fetchResultEquity(runId: string, resultId: string): Promise<EquityPoint[]> {
  const res = await fetch(`${API_BASE}/optimizations/${runId}/results/${resultId}/equity`)
  if (!res.ok) throw new Error(`GET opt equity failed: ${res.status}`)
  return res.json()
}

// ----------------------------- Component ------------------------------------

export default function OptimizationsPage() {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null)
  const [axisX, setAxisX] = useState<AxisOption>('atr_stop_mult')
  const [axisY, setAxisY] = useState<AxisOption>('opening_range_minutes')

  // Fetch run list — poll every 2s while any run is still "running"
  const {
    data: runs,
    isLoading: runsLoading,
    error: runsError,
  } = useQuery<OptRun[]>({
    queryKey: ['optimizations'],
    queryFn: fetchRuns,
    refetchInterval: (query) => {
      const data = query.state.data
      if (Array.isArray(data) && data.some((r) => r.status === 'running')) {
        return 2000
      }
      return false
    },
  })

  // Fetch results for selected run
  const { data: results, isLoading: resultsLoading } = useQuery<OptResult[]>({
    queryKey: ['opt-results', selectedRunId],
    queryFn: () => fetchResults(selectedRunId!),
    enabled: selectedRunId !== null,
    refetchInterval: () => {
      const run = runs?.find((r) => r.run_id === selectedRunId)
      return run?.status === 'running' ? 2000 : false
    },
  })

  // Fetch heatmap for selected run + axes
  const { data: heatmapData, isLoading: heatmapLoading } =
    useQuery<HeatmapData>({
      queryKey: ['opt-heatmap', selectedRunId, axisX, axisY],
      queryFn: () => fetchHeatmap(selectedRunId!, axisX, axisY),
      enabled: selectedRunId !== null,
    })

  // Fetch OOS equity curve for selected result row
  const { data: resultEquity } = useQuery<EquityPoint[]>({
    queryKey: ['opt-result-equity', selectedRunId, selectedResultId],
    queryFn: () => fetchResultEquity(selectedRunId!, selectedResultId!),
    enabled: selectedRunId !== null && selectedResultId !== null,
  })

  // ----------------------------- Render -------------------------------------

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: '#000000',
        color: '#d1d4dc',
        fontFamily: 'monospace',
      }}
    >
      {/* Header */}
      <header
        style={{
          height: '48px',
          display: 'flex',
          alignItems: 'center',
          gap: '16px',
          padding: '0 16px',
          borderBottom: '1px solid #222222',
          flexShrink: 0,
        }}
      >
        <Link
          href="/dashboard"
          style={{
            color: '#888',
            textDecoration: 'none',
            fontSize: '12px',
          }}
        >
          &larr; Dashboard
        </Link>
        <span
          style={{ color: '#d1d4dc', fontWeight: 'bold', fontSize: '14px' }}
        >
          Optimization Results
        </span>
      </header>

      <div style={{ padding: '16px', maxWidth: '1200px' }}>
        {/* Error state */}
        {runsError && (
          <div
            style={{
              color: '#fca5a5',
              backgroundColor: '#7f1d1d',
              padding: '8px 12px',
              borderRadius: '4px',
              marginBottom: '16px',
              fontSize: '12px',
            }}
          >
            Failed to load optimization runs. Is the API running?
          </div>
        )}

        {/* Loading state */}
        {runsLoading && (
          <div style={{ color: '#888', fontSize: '12px', marginBottom: '16px' }}>
            Loading runs...
          </div>
        )}

        {/* Run selector */}
        {runs && runs.length > 0 && (
          <div style={{ marginBottom: '16px' }}>
            <label
              style={{
                fontSize: '11px',
                color: '#888',
                display: 'block',
                marginBottom: '6px',
              }}
            >
              SELECT RUN
            </label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {runs.map((run) => (
                <button
                  key={run.run_id}
                  onClick={() => setSelectedRunId(run.run_id)}
                  style={{
                    textAlign: 'left',
                    backgroundColor:
                      selectedRunId === run.run_id ? '#1a1a2e' : '#111',
                    border: `1px solid ${selectedRunId === run.run_id ? '#4a90d9' : '#333'}`,
                    color: '#d1d4dc',
                    padding: '8px 12px',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontSize: '12px',
                    fontFamily: 'monospace',
                  }}
                >
                  <span style={{ color: '#4a90d9' }}>
                    {run.run_id.slice(0, 8)}
                  </span>
                  {'  '}
                  <span style={{ color: '#888' }}>{run.strategy_id}</span>
                  {'  '}
                  <span
                    style={{
                      color:
                        run.status === 'complete'
                          ? '#4ade80'
                          : run.status === 'running'
                            ? '#facc15'
                            : '#f87171',
                    }}
                  >
                    {run.status}
                  </span>
                  {'  '}
                  <span style={{ color: '#555' }}>
                    {run.completed_combos}/{run.total_combos} combos &middot;{' '}
                    {new Date(run.created_at).toLocaleDateString()}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {runs && runs.length === 0 && !runsLoading && (
          <div
            style={{
              color: '#555',
              fontSize: '12px',
              padding: '32px 0',
              textAlign: 'center',
            }}
          >
            No optimization runs found. Run <code>python scripts/run_opt.py</code>{' '}
            to create one.
          </div>
        )}

        {/* Results section */}
        {selectedRunId && (
          <>
            {/* Leaderboard table */}
            <div style={{ marginBottom: '24px' }}>
              <div
                style={{
                  fontSize: '11px',
                  color: '#888',
                  marginBottom: '8px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                Leaderboard — OOS Sharpe Ranked
              </div>

              {resultsLoading && (
                <div style={{ color: '#555', fontSize: '12px' }}>
                  Loading results...
                </div>
              )}

              {results && results.length === 0 && !resultsLoading && (
                <div style={{ color: '#555', fontSize: '12px' }}>
                  No results yet — run may still be in progress.
                </div>
              )}

              {results && results.length > 0 && (
                <div style={{ overflowX: 'auto' }}>
                  <table
                    style={{
                      width: '100%',
                      borderCollapse: 'collapse',
                      fontSize: '11px',
                    }}
                  >
                    <thead>
                      <tr style={{ color: '#666', borderBottom: '1px solid #222' }}>
                        <th style={thStyle}>#</th>
                        <th style={thStyle}>Hash</th>
                        <th style={thStyle}>OR Min</th>
                        <th style={thStyle}>ATR Mult</th>
                        <th style={thStyle}>R Target</th>
                        <th style={thStyle}>OOS Sharpe</th>
                        <th style={thStyle}>IS Sharpe</th>
                        <th style={thStyle}>IS/OOS Edge</th>
                        <th style={thStyle}>OOS Return</th>
                        <th style={thStyle}>Fold</th>
                      </tr>
                    </thead>
                    <tbody>
                      {results.map((row, idx) => {
                        // edge_ratio > 2 = overfitting red flag (OPT-07)
                        const edgeFlagged =
                          row.edge_ratio !== null && row.edge_ratio > 2.0
                        const isSelected = selectedResultId === row.result_id
                        return (
                          <tr
                            key={row.result_id}
                            onClick={() => setSelectedResultId(row.result_id)}
                            style={{
                              borderBottom: '1px solid #1a1a1a',
                              backgroundColor: isSelected
                                ? '#0d1f3c'
                                : idx % 2 === 0 ? '#050505' : '#000',
                              cursor: 'pointer',
                              outline: isSelected ? '1px solid #4a90d9' : 'none',
                            }}
                          >
                            <td style={tdStyle}>{idx + 1}</td>
                            <td style={{ ...tdStyle, color: '#4a90d9' }}>
                              {row.param_hash.slice(0, 8)}
                            </td>
                            <td style={tdStyle}>{row.opening_range_minutes}</td>
                            <td style={tdStyle}>{row.atr_stop_mult}</td>
                            <td style={tdStyle}>{row.r_target}</td>
                            <td
                              style={{
                                ...tdStyle,
                                color:
                                  row.oos_sharpe !== null &&
                                  row.oos_sharpe > 0
                                    ? '#4ade80'
                                    : '#f87171',
                                fontWeight: 'bold',
                              }}
                            >
                              {row.oos_sharpe !== null
                                ? row.oos_sharpe.toFixed(3)
                                : '—'}
                            </td>
                            <td style={tdStyle}>
                              {row.is_sharpe !== null
                                ? row.is_sharpe.toFixed(3)
                                : '—'}
                            </td>
                            {/* edge_ratio > 2.0 → red flag for overfitting (OPT-07 / T-04-03-01) */}
                            <td
                              style={{
                                ...tdStyle,
                                ...(edgeFlagged
                                  ? {
                                      backgroundColor: '#7f1d1d',
                                      color: '#fca5a5',
                                    }
                                  : {}),
                              }}
                            >
                              {row.edge_ratio !== null
                                ? row.edge_ratio.toFixed(2)
                                : '—'}
                            </td>
                            <td style={tdStyle}>
                              {row.oos_return !== null
                                ? `${(row.oos_return * 100).toFixed(1)}%`
                                : '—'}
                            </td>
                            <td style={{ ...tdStyle, color: '#888' }}>
                              {row.fold_idx}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Axis selectors + heatmap */}
            <div style={{ marginBottom: '24px' }}>
              <div
                style={{
                  fontSize: '11px',
                  color: '#888',
                  marginBottom: '8px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                2-Param Heatmap — OOS Sharpe
              </div>

              <div
                style={{
                  display: 'flex',
                  gap: '16px',
                  marginBottom: '12px',
                  alignItems: 'center',
                }}
              >
                <div>
                  <label
                    style={{
                      fontSize: '10px',
                      color: '#666',
                      display: 'block',
                      marginBottom: '4px',
                    }}
                  >
                    X AXIS
                  </label>
                  <select
                    value={axisX}
                    onChange={(e) => setAxisX(e.target.value as AxisOption)}
                    style={selectStyle}
                  >
                    {AXIS_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label
                    style={{
                      fontSize: '10px',
                      color: '#666',
                      display: 'block',
                      marginBottom: '4px',
                    }}
                  >
                    Y AXIS
                  </label>
                  <select
                    value={axisY}
                    onChange={(e) => setAxisY(e.target.value as AxisOption)}
                    style={selectStyle}
                  >
                    {AXIS_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                </div>

                {heatmapLoading && (
                  <div style={{ color: '#555', fontSize: '12px', marginTop: '14px' }}>
                    Loading heatmap...
                  </div>
                )}
              </div>

              {/* Plotly heatmap — only when data is available and non-empty */}
              {heatmapData && heatmapData.z.length > 0 && (
                <Suspense
                  fallback={
                    <div style={{ color: '#555', fontSize: '12px' }}>
                      Loading chart...
                    </div>
                  }
                >
                  <Plot
                    data={[
                      {
                        type: 'heatmap',
                        z: heatmapData.z,
                        x: heatmapData.x,
                        y: heatmapData.y,
                        colorscale: 'RdYlGn',
                        zmin: -1,
                      },
                    ]}
                    layout={{
                      title: { text: 'OOS Sharpe — 2-Param Heatmap' },
                      xaxis: { title: { text: axisX } },
                      yaxis: { title: { text: axisY } },
                      paper_bgcolor: '#0a0a0a',
                      plot_bgcolor: '#111',
                      font: { color: '#e0e0e0' },
                      width: 600,
                      height: 400,
                    }}
                    config={{ displayModeBar: false }}
                  />
                </Suspense>
              )}

              {/* Placeholder when heatmap is empty but loaded */}
              {heatmapData && heatmapData.z.length === 0 && !heatmapLoading && (
                <div
                  style={{
                    color: '#555',
                    fontSize: '12px',
                    padding: '24px',
                    border: '1px dashed #222',
                    borderRadius: '4px',
                    textAlign: 'center',
                  }}
                >
                  No heatmap data — run may still be in progress or has no results
                  for these axes.
                </div>
              )}
            </div>

            {/* OOS Equity Curve for selected result row */}
            <div style={{ marginBottom: '24px' }}>
              <div
                style={{
                  fontSize: '11px',
                  color: '#888',
                  marginBottom: '8px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                OOS Equity Curve
                {selectedResultId
                  ? ' — click a row above to change'
                  : ' — click a row above to view'}
              </div>

              {!selectedResultId && (
                <div
                  style={{
                    color: '#444',
                    fontSize: '12px',
                    padding: '24px',
                    border: '1px dashed #222',
                    borderRadius: '4px',
                    textAlign: 'center',
                  }}
                >
                  Select a result row to view its OOS equity curve
                </div>
              )}

              {selectedResultId && resultEquity && resultEquity.length > 0 && (
                <div style={{ height: '240px', border: '1px solid #1a1a1a', borderRadius: '4px', overflow: 'hidden' }}>
                  <EquityCurve points={resultEquity} />
                </div>
              )}

              {selectedResultId && resultEquity && resultEquity.length === 0 && (
                <div style={{ color: '#555', fontSize: '12px', padding: '24px', textAlign: 'center', border: '1px dashed #222', borderRadius: '4px' }}>
                  No equity data for this result
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ----------------------------- Style constants --------------------------------

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 10px',
  fontWeight: 'normal',
  whiteSpace: 'nowrap',
}

const tdStyle: React.CSSProperties = {
  padding: '5px 10px',
  whiteSpace: 'nowrap',
}

const selectStyle: React.CSSProperties = {
  backgroundColor: '#111',
  border: '1px solid #333',
  color: '#d1d4dc',
  padding: '4px 8px',
  borderRadius: '4px',
  fontSize: '12px',
  fontFamily: 'monospace',
  cursor: 'pointer',
}
