'use client'

/**
 * ConfirmationDialog — extracted from apps/web/app/dashboard/blotter/page.tsx (Phase 5).
 *
 * Standalone reusable confirmation dialog with typed input guard.
 * Requires the user to type an exact string (e.g. "FLATTEN" or "KILL")
 * before enabling the confirm button.
 *
 * Used by: BlotterPane (Phase 7), and any future destructive action dialogs.
 */

import { useState, useEffect, useRef } from 'react'

interface ConfirmDialogProps {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  titleColor: string
  description: string
  warning: string
  inputLabel: string
  confirmString: string
  confirmButtonText: string
  dismissButtonText: string
  confirmBorderColor: string
  inputErrorBorderColor: string
}

export default function ConfirmationDialog({
  open,
  onClose,
  onConfirm,
  title,
  titleColor,
  description,
  warning,
  inputLabel,
  confirmString,
  confirmButtonText,
  dismissButtonText,
  confirmBorderColor,
  inputErrorBorderColor,
}: ConfirmDialogProps) {
  const [value, setValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const titleId = `dialog-title-${title.replace(/\s+/g, '-').toLowerCase()}`

  // Reset input and auto-focus on open
  useEffect(() => {
    if (open) {
      setValue('')
      // Small timeout ensures DOM is rendered before focus
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [open])

  // Escape closes dialog
  useEffect(() => {
    if (!open) return
    function handler(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Enter' && value === confirmString) {
        e.preventDefault()  // WR-06: prevent button onClick from also firing when button has focus
        onConfirm()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, value, confirmString, onClose, onConfirm])

  if (!open) return null

  const isConfirmable = value === confirmString
  const hasError = value.length > 0 && !isConfirmable
  const inputBorderColor = hasError ? inputErrorBorderColor : '#333333'

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.75)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        style={{
          backgroundColor: '#111111',
          border: '1px solid #333333',
          borderRadius: '4px',
          padding: '24px',
          maxWidth: '480px',
          width: '100%',
          fontFamily: 'monospace',
        }}
      >
        {/* Title */}
        <div
          id={titleId}
          style={{
            fontSize: '14px',
            fontWeight: 'bold',
            color: titleColor,
            marginBottom: '16px',
          }}
        >
          {title}
        </div>

        {/* Description */}
        <div style={{ fontSize: '12px', color: '#888888', marginBottom: '16px' }}>
          {description}
        </div>

        {/* Warning */}
        <div style={{ fontSize: '12px', color: '#f87171', marginBottom: '16px' }}>
          {warning}
        </div>

        {/* Input label */}
        <div style={{ fontSize: '11px', color: '#888888', marginBottom: '8px' }}>
          {inputLabel}
        </div>

        {/* Input */}
        <input
          ref={inputRef}
          type="text"
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          style={{
            fontSize: '12px',
            fontFamily: 'monospace',
            backgroundColor: '#000000',
            border: `1px solid ${inputBorderColor}`,
            borderRadius: '4px',
            color: '#d1d4dc',
            padding: '8px 12px',
            width: '100%',
            boxSizing: 'border-box',
            outline: 'none',
          }}
        />

        {/* Button row */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '8px',
            marginTop: '16px',
          }}
        >
          <button
            onClick={onClose}
            tabIndex={0}
            style={{
              border: '1px solid #444444',
              color: '#888888',
              backgroundColor: 'transparent',
              fontSize: '12px',
              fontFamily: 'monospace',
              padding: '4px 12px',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            {dismissButtonText}
          </button>
          <button
            onClick={isConfirmable ? onConfirm : undefined}
            disabled={!isConfirmable}
            aria-disabled={!isConfirmable}
            tabIndex={0}
            style={{
              border: isConfirmable
                ? `1px solid ${confirmBorderColor}`
                : '1px solid #444444',
              color: isConfirmable ? confirmBorderColor : '#555555',
              backgroundColor: 'transparent',
              fontSize: '12px',
              fontFamily: 'monospace',
              padding: '4px 12px',
              borderRadius: '4px',
              cursor: isConfirmable ? 'pointer' : 'not-allowed',
            }}
          >
            {confirmButtonText}
          </button>
        </div>
      </div>
    </div>
  )
}
