import { apiClient } from '@/lib/apiClient'

export interface LoginResponse {
  access_token: string
  token_type: string
}

export function login(email: string, password: string) {
  return apiClient.post<LoginResponse>('/auth/login', { email, password })
}
