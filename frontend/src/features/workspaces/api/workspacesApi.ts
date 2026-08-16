import { apiClient } from '@/lib/apiClient'

export interface WorkspaceSummary {
  id: string
  name: string
  slug: string
  role: 'admin' | 'member'
}

export function createWorkspace(name: string) {
  return apiClient.post<WorkspaceSummary>('/workspaces', { name })
}
