import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Group, Paper, SimpleGrid, Stack, Table, Text } from '@mantine/core'
import { IconBrandMatrix, IconBrandTelegram, IconMessageCircle, IconRefresh, IconSend, IconSettings } from '@tabler/icons-react'
import { ErrorBanner, LoadingSpinner, PageHead, formatDateTime, useT, useToast } from '@hubra/plugin-sdk'
import { QK, errorText, getLog, getStatus, retry, sendTest, type Channel, type LogRow } from './api'

const ICONS: Record<Channel, typeof IconBrandTelegram> = {
  telegram: IconBrandTelegram,
  signal: IconMessageCircle,
  matrix: IconBrandMatrix,
}
const NAMES: Record<Channel, string> = { telegram: 'Telegram', signal: 'Signal', matrix: 'Matrix' }
const STATUS_COLORS: Record<LogRow['status'], string> = { queued: 'blue', sent: 'green', failed: 'red' }

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** Which messengers are set up, a test message, and what was sent. */
export function MessengersScreen() {
  const { t } = useT()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { notify } = useToast()
  const status = useQuery({ queryKey: QK.status, queryFn: getStatus })
  const log = useQuery({ queryKey: QK.log, queryFn: getLog })
  const [busy, setBusy] = useState<string | null>(null)

  const run = async (key: string, fn: () => Promise<LogRow>) => {
    setBusy(key)
    try {
      const row = await fn()
      if (row.status === 'sent') notify('success', t('messengers.sentToast', { name: NAMES[row.channel] }))
      else notify('error', t('messengers.failedToast', { name: NAMES[row.channel], error: row.error ?? '' }))
    } catch (err) {
      notify('error', errorText(err))
    } finally {
      setBusy(null)
      qc.invalidateQueries({ queryKey: QK.status })
      qc.invalidateQueries({ queryKey: QK.log })
    }
  }

  const err = status.error || log.error
  if (err) return <ErrorBanner message={errorText(err)} onRetry={() => (status.refetch(), log.refetch())} />
  if (!status.data || !log.data) return <LoadingSpinner />
  const s = status.data
  const on = (['event', 'post', 'poll', 'reminder'] as const).filter((k) => s.announce[k])

  return (
    <>
      <PageHead
        title={t('messengers.title')}
        desc={t('messengers.desc')}
        actions={
          <Button variant="default" leftSection={<IconSettings size={16} />} onClick={() => navigate('/app/settings/modules?module=messengers')}>
            {t('messengers.settings')}
          </Button>
        }
      />
      <Stack gap="lg">
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
          {s.channels.map((c) => {
            const Icon = ICONS[c.channel]
            return (
              <Paper key={c.channel} withBorder radius="md" p="md">
                <Group justify="space-between" wrap="nowrap" mb={6}>
                  <Group gap={8} wrap="nowrap">
                    <Icon size={22} />
                    <Text fw={700}>{NAMES[c.channel]}</Text>
                  </Group>
                  <Badge size="sm" variant="light" color={c.configured ? 'green' : 'gray'} style={{ textTransform: 'none' }}>
                    {c.configured ? t('messengers.ready') : t('messengers.notSetUp')}
                  </Badge>
                </Group>
                <Text size="sm" c="dimmed" mb="xs">
                  {c.lastSentAt
                    ? t('messengers.lastSent', { when: formatDateTime(c.lastSentAt) })
                    : c.configured
                      ? t('messengers.nothingYet')
                      : t(`messengers.howTo.${c.channel}`)}
                </Text>
                {c.lastError && (
                  <Text size="sm" c="red" mb="xs">
                    {t('messengers.lastError', { error: c.lastError })}
                  </Text>
                )}
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<IconSend size={14} />}
                  disabled={!c.configured}
                  loading={busy === c.channel}
                  onClick={() => run(c.channel, () => sendTest(c.channel))}
                >
                  {t('messengers.test')}
                </Button>
              </Paper>
            )
          })}
        </SimpleGrid>

        <Paper withBorder radius="md" p="md">
          <Text fw={700} mb={4}>
            {t('messengers.whatTitle')}
          </Text>
          <Text size="sm" c="dimmed">
            {capitalize(on.length ? on.map((k) => t(`messengers.kind.${k}`)).join(', ') : t('messengers.nothingOn'))}
            {'. '}
            {s.membersOnlyEvents ? t('messengers.membersOnlyOn') : t('messengers.membersOnlyOff')}
          </Text>
        </Paper>

        <section>
          <Text fw={700} mb="xs">
            {t('messengers.logTitle')}
          </Text>
          {!log.data.length ? (
            <Text size="sm" c="dimmed">
              {t('messengers.logEmpty')}
            </Text>
          ) : (
            <Paper withBorder radius="md" p={0} style={{ overflowX: 'auto' }}>
              <Table verticalSpacing="xs" horizontalSpacing="md">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t('messengers.when')}</Table.Th>
                    <Table.Th>{t('messengers.where')}</Table.Th>
                    <Table.Th>{t('messengers.what')}</Table.Th>
                    <Table.Th>{t('messengers.state')}</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {log.data.map((r) => (
                    <Table.Tr key={r.id}>
                      <Table.Td style={{ whiteSpace: 'nowrap' }}>{formatDateTime(r.sentAt ?? r.createdAt ?? '')}</Table.Td>
                      <Table.Td>{NAMES[r.channel]}</Table.Td>
                      <Table.Td>
                        <Text size="sm" lineClamp={1}>
                          {r.title}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {t(`messengers.kind.${r.kind}`)}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={6} wrap="nowrap">
                          <Badge size="sm" variant="light" color={STATUS_COLORS[r.status]} style={{ textTransform: 'none' }}>
                            {t(`messengers.status.${r.status}`)}
                          </Badge>
                          {r.status === 'failed' && (
                            <Button
                              size="compact-xs"
                              variant="subtle"
                              leftSection={<IconRefresh size={12} />}
                              loading={busy === `r${r.id}`}
                              onClick={() => run(`r${r.id}`, () => retry(r.id))}
                            >
                              {t('messengers.retry')}
                            </Button>
                          )}
                        </Group>
                        {r.error && (
                          <Text size="xs" c="red">
                            {r.error}
                          </Text>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Paper>
          )}
        </section>
      </Stack>
    </>
  )
}
