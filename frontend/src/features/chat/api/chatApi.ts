import { apiClient } from '@/lib/apiClient'

export interface Citation {
  document_id: string
  document_title: string
  chunk_id: string
  chunk_text_snippet: string
  score: number
  source_url: string
  version_number: number
}

export interface ChatResponse {
  session_id: string
  answer: string
  citations: Citation[]
}

export function sendChatMessage(message: string, sessionId: string | null) {
  return apiClient.post<ChatResponse>('/chat', { session_id: sessionId, message })
}
