import { useState } from 'react'
import { Check, Globe, Link as LinkIcon, Lock } from 'lucide-react'

import * as agentApi from '@/api/agent'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover'
import { ShareIcon } from '@/components/icons'
import { cn } from '@/lib/utils'
import { copyToClipboard } from '@/utils/dom'
import { showErrorToast, showSuccessToast } from '@/utils/toast'

interface Props {
  sessionId: string | undefined
  shareMode: 'private' | 'public'
  onShareModeChange: (mode: 'private' | 'public') => void
}

/**
 * Header share popover. Pulled out of ChatPage so the page focuses on layout
 * and stream wiring instead of ~140 lines of menu chrome. Owns its own
 * sharing-busy + link-copied transient state — neither matters outside the
 * popover.
 */
export default function ShareMenu({ sessionId, shareMode, onShareModeChange }: Props) {
  const [sharingLoading, setSharingLoading] = useState(false)
  const [linkCopied, setLinkCopied] = useState(false)

  const handleShareModeChange = async (mode: 'private' | 'public') => {
    if (!sessionId || sharingLoading) return
    if (shareMode === mode) {
      setLinkCopied(false)
      return
    }
    try {
      setSharingLoading(true)
      if (mode === 'public') await agentApi.shareSession(sessionId)
      else await agentApi.unshareSession(sessionId)
      onShareModeChange(mode)
      setLinkCopied(false)
    } catch (e) {
      console.error('Error changing share mode:', e)
      showErrorToast('Failed to change sharing settings')
    } finally {
      setSharingLoading(false)
    }
  }

  const handleInstantShare = async () => {
    if (!sessionId) return
    setSharingLoading(true)
    try {
      await agentApi.shareSession(sessionId)
      onShareModeChange('public')
      setLinkCopied(false)
    } catch (e) {
      console.error('Error sharing session:', e)
      showErrorToast('Failed to share session')
    } finally {
      setSharingLoading(false)
    }
  }

  const handleCopyLink = async () => {
    if (!sessionId) return
    const shareUrl = `${window.location.origin}/share/${sessionId}`
    const ok = await copyToClipboard(shareUrl)
    if (ok) {
      setLinkCopied(true)
      window.setTimeout(() => setLinkCopied(false), 3000)
      showSuccessToast('Link copied to clipboard')
    } else {
      showErrorToast('Failed to copy link')
    }
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className="h-8 px-3 rounded-[100px] inline-flex items-center gap-1 cursor-pointer outline outline-1 outline-offset-[-1px] outline-[var(--border-btn-main)] hover:bg-[var(--fill-tsp-white-light)] me-1.5">
          <ShareIcon color="var(--icon-secondary)" />
          <span className="text-[var(--text-secondary)] text-sm font-medium">Share</span>
        </button>
      </PopoverTrigger>
      <PopoverContent>
        <div
          className="w-[400px] flex flex-col rounded-2xl bg-[var(--background-menu-white)] shadow-[0px_8px_32px_0px_var(--shadow-S),0px_0px_0px_1px_var(--border-light)]"
          style={{ maxWidth: 'calc(-16px + 100vw)' }}
        >
          <div className="flex flex-col pt-[12px] px-[16px] pb-[16px]">
            <ShareModeRow
              icon="lock"
              title="Private Only"
              subtitle="Only visible to you"
              active={shareMode === 'private'}
              disabled={sharingLoading}
              onClick={() => handleShareModeChange('private')}
            />
            <ShareModeRow
              icon="globe"
              title="Public Access"
              subtitle="Anyone with the link can view"
              active={shareMode === 'public'}
              disabled={sharingLoading}
              onClick={() => handleShareModeChange('public')}
            />
            <div className="border-t border-[var(--border-main)] mt-[4px]" />
            {shareMode === 'private' ? (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  void handleInstantShare()
                }}
                disabled={sharingLoading}
                className="inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors hover:opacity-90 bg-[var(--Button-primary-black)] text-[var(--text-onblack)] h-[36px] px-[12px] rounded-[10px] gap-[6px] text-sm w-full mt-[16px] disabled:opacity-50"
              >
                {sharingLoading ? (
                  <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : (
                  <LinkIcon size={16} stroke="currentColor" strokeWidth={2} />
                )}
                {sharingLoading ? 'Sharing...' : 'Share Instantly'}
              </button>
            ) : (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  void handleCopyLink()
                }}
                className={cn(
                  'inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors h-[36px] px-[12px] rounded-[10px] gap-[6px] text-sm w-full mt-[16px]',
                  linkCopied
                    ? 'bg-[var(--Button-primary-white)] text-[var(--text-primary)] hover:opacity-70 border border-[var(--border-btn-main)]'
                    : 'bg-[var(--Button-primary-black)] text-[var(--text-onblack)] hover:opacity-90',
                )}
              >
                {linkCopied ? (
                  <Check size={16} color="var(--text-primary)" />
                ) : (
                  <LinkIcon size={16} stroke="currentColor" strokeWidth={2} />
                )}
                {linkCopied ? 'Link Copied' : 'Copy Link'}
              </button>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

interface RowProps {
  icon: 'lock' | 'globe'
  title: string
  subtitle: string
  active: boolean
  disabled: boolean
  onClick: () => void
}

function ShareModeRow({ icon, title, subtitle, active, disabled, onClick }: RowProps) {
  const Icon = icon === 'lock' ? Lock : Globe
  return (
    <div
      onClick={onClick}
      className={cn(
        'flex items-center gap-[10px] px-[8px] -mx-[8px] py-[8px] rounded-[8px] cursor-pointer hover:bg-[var(--fill-tsp-white-main)]',
        disabled && 'pointer-events-none opacity-50',
      )}
    >
      <div
        className={cn(
          'w-[32px] h-[32px] rounded-[8px] flex items-center justify-center',
          active ? 'bg-[var(--Button-primary-black)]' : 'bg-[var(--fill-tsp-white-dark)]',
        )}
      >
        <Icon
          size={16}
          stroke={active ? 'var(--text-onblack)' : 'var(--icon-primary)'}
          strokeWidth={2}
        />
      </div>
      <div className="flex flex-col flex-1 min-w-0">
        <div className="text-sm font-medium text-[var(--text-primary)]">{title}</div>
        <div className="text-[13px] text-[var(--text-tertiary)]">{subtitle}</div>
      </div>
      <Check
        size={20}
        className={cn(active ? 'ml-auto' : 'ml-auto invisible')}
        color={active ? 'var(--icon-primary)' : 'var(--icon-tertiary)'}
      />
    </div>
  )
}
