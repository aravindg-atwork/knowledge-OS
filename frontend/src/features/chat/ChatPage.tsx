import { useState } from 'react'
import { Send } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/apiClient'
import { DocumentViewerModal } from '@/features/documents/components/DocumentViewerModal'
import { ChatMessage, type ChatMessageData } from './components/ChatMessage'
import { sendChatMessage } from './api/chatApi'

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessageData[]>([])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [viewer, setViewer] = useState<{ id: string; title: string } | null>(null)

  async function handleSend(event: React.FormEvent) {
    event.preventDefault()
    const question = input.trim()
    if (!question || sending) return

    const userMessage: ChatMessageData = {
      id: crypto.randomUUID(),
      role: 'user',
      content: question,
    }
    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setSending(true)

    try {
      const response = await sendChatMessage(question, sessionId)
      setSessionId(response.session_id)
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: response.answer,
          citations: response.citations,
        },
      ])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content:
            err instanceof ApiError
              ? `Something went wrong: ${err.message}`
              : 'Something went wrong answering that question.',
        },
      ])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="mx-auto flex h-screen max-w-3xl flex-col px-6 py-6">
      <h1 className="mb-4 text-lg font-semibold">Ask the Knowledge Hub</h1>

      <div className="flex-1 space-y-4 overflow-y-auto pb-4">
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Ask about anything synchronized from Google Drive &mdash; e.g. &ldquo;Where is the
            Payment API documentation?&rdquo;
          </p>
        )}
        {messages.map((message) => (
          <ChatMessage
            key={message.id}
            message={message}
            onOpenDocument={(id, title) => setViewer({ id, title })}
          />
        ))}
        {sending && <p className="text-sm text-muted-foreground">Thinking...</p>}
      </div>

      <form onSubmit={handleSend} className="flex gap-2 border-t border-border pt-4">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question..."
          disabled={sending}
        />
        <Button type="submit" disabled={sending || !input.trim()}>
          <Send size={16} />
        </Button>
      </form>

      <DocumentViewerModal
        documentId={viewer?.id ?? null}
        title={viewer?.title ?? ''}
        onClose={() => setViewer(null)}
      />
    </div>
  )
}
