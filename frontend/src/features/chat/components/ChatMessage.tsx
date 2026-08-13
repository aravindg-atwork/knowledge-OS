import { cn } from '@/lib/utils'
import { CitationBadge } from './CitationBadge'
import type { Citation } from '../api/chatApi'

export interface ChatMessageData {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}

interface ChatMessageProps {
  message: ChatMessageData
  onOpenDocument: (documentId: string, title: string) => void
}

export function ChatMessage({ message, onOpenDocument }: ChatMessageProps) {
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-2xl rounded-lg px-4 py-3 text-sm leading-relaxed',
          isUser ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground',
        )}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        {message.citations && message.citations.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2 border-t border-border/50 pt-3">
            {message.citations.map((citation, index) => (
              <CitationBadge
                key={citation.chunk_id}
                citation={citation}
                index={index}
                onOpen={onOpenDocument}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
