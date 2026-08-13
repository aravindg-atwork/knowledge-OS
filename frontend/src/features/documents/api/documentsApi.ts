import { apiClient } from '@/lib/apiClient'

export interface DocumentSummary {
  id: string
  title: string
  mime_type: string
  source_url: string
  version_number: number | null
  updated_at: string
}

export function listDocuments() {
  return apiClient.get<DocumentSummary[]>('/documents')
}
