import { apiFetch } from '@hubra/plugin-sdk'

export type Channel = 'telegram' | 'signal' | 'matrix'
export type Kind = 'event' | 'post' | 'poll' | 'reminder' | 'test'

export interface Status {
  channels: { channel: Channel; configured: boolean; lastSentAt: string | null; lastError: string | null }[]
  announce: Record<'event' | 'post' | 'poll' | 'reminder', boolean>
  membersOnlyEvents: boolean
}

export interface LogRow {
  id: number
  channel: Channel
  kind: Kind
  title: string
  status: 'queued' | 'sent' | 'failed'
  error: string | null
  tries: number
  createdAt: string | null
  sentAt: string | null
}

export const QK = {
  status: ['messengers', 'status'] as const,
  log: ['messengers', 'log'] as const,
}

const BASE = '/app/messengers'
const post = (body?: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body ?? {}),
})

export const getStatus = () => apiFetch<Status>(`${BASE}/status`)
export const getLog = () => apiFetch<LogRow[]>(`${BASE}/log`)
export const sendTest = (channel: Channel) => apiFetch<LogRow>(`${BASE}/test`, post({ channel }))
export const retry = (id: number) => apiFetch<LogRow>(`${BASE}/log/${id}/retry`, post())

export function errorText(err: unknown) {
  return err instanceof Error ? err.message : String(err)
}
