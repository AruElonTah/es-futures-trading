'use client'

/**
 * PaneContainer — shared pane chrome for the 4-pane terminal layout (Phase 7).
 *
 * Renders a 28px title bar (D-05) with label + optional rightSlot, and a
 * content area that fills remaining height. Each pane controls its own
 * internal scroll.
 *
 * Design tokens (07-UI-SPEC.md):
 *   - Title bar height: 28px
 *   - Title bar background: #111111 (secondary)
 *   - Title bar border: 1px solid #222222
 *   - Label: 14px bold #d1d4dc monospace, letterSpacing 0.08em
 *   - rightSlot: right-aligned flex, gap 8px
 */

import React from 'react'

interface PaneContainerProps {
  label: string
  rightSlot?: React.ReactNode
  children: React.ReactNode
}

export default function PaneContainer({ label, rightSlot, children }: PaneContainerProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        backgroundColor: '#000000',
        overflow: 'hidden',
      }}
    >
      {/* 28px title bar — D-05 */}
      <div
        style={{
          height: '28px',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 8px',
          borderBottom: '1px solid #222222',
          backgroundColor: '#111111',
        }}
      >
        <span
          style={{
            fontSize: '14px',
            fontWeight: 'bold',
            fontFamily: 'monospace',
            color: '#d1d4dc',
            letterSpacing: '0.08em',
          }}
        >
          {label}
        </span>
        {rightSlot && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {rightSlot}
          </div>
        )}
      </div>
      {/* Content fills remaining height */}
      <div style={{ flex: '1 1 0', overflow: 'hidden', minHeight: 0 }}>
        {children}
      </div>
    </div>
  )
}
