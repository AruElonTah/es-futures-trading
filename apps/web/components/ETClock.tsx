'use client'

/**
 * ETClock — displays current America/New_York wall-clock time, ticking every 1s.
 *
 * Uses Intl.DateTimeFormat with timeZone: 'America/New_York' for DST-correct display.
 * 24h format (hour12: false) per the Bloomberg-terminal convention.
 */

import { useState, useEffect } from 'react'

const etFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

function formatET(): string {
  return etFormatter.format(new Date())
}

export default function ETClock() {
  const [time, setTime] = useState<string>(() => formatET())

  useEffect(() => {
    const interval = setInterval(() => {
      setTime(formatET())
    }, 1000)
    return () => clearInterval(interval)
  }, [])

  return (
    <span
      className="font-mono text-sm tabular-nums"
      title="America/New_York"
    >
      {time} ET
    </span>
  )
}
