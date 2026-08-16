import { apiClient } from '@/lib/apiClient'

export interface WorkspaceSummary {
  id: string
  name: string
  slug: string
  role: 'admin' | 'member'
}

export function updateWorkspace(name: string) {
  return apiClient.patch<WorkspaceSummary>('/workspaces/current', { name })
}

export interface Member {
  user_id: string
  email: string
  full_name: string | null
  role: 'admin' | 'member'
}

export function listMembers() {
  return apiClient.get<Member[]>('/workspaces/current/members')
}

export function updateMemberRole(userId: string, role: 'admin' | 'member') {
  return apiClient.patch<Member>(`/workspaces/current/members/${userId}`, { role })
}

export function removeMember(userId: string) {
  return apiClient.delete<void>(`/workspaces/current/members/${userId}`)
}

export interface Invitation {
  id: string
  email: string
  role: 'admin' | 'member'
  expires_at: string
}

export function listInvitations() {
  return apiClient.get<Invitation[]>('/invitations')
}

export function createInvitation(email: string, role: 'admin' | 'member') {
  return apiClient.post<Invitation>('/invitations', { email, role })
}

export function revokeInvitation(id: string) {
  return apiClient.delete<void>(`/invitations/${id}`)
}
