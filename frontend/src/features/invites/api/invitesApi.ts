import { apiClient } from '@/lib/apiClient'

export interface InvitePreview {
  workspace_name: string
  email: string
}

export function previewInvite(token: string) {
  return apiClient.get<InvitePreview>(`/invitations/preview?token=${encodeURIComponent(token)}`)
}

export interface AcceptInviteResponse {
  access_token: string
  token_type: string
}

export function acceptInvite(params: { token: string; password?: string; full_name?: string }) {
  return apiClient.post<AcceptInviteResponse>('/invitations/accept', params)
}
