import { apiClient } from '@/lib/apiClient'

export interface LoginResponse {
  access_token: string
  token_type: string
}

export function login(email: string, password: string) {
  return apiClient.post<LoginResponse>('/auth/login', { email, password })
}

export interface SignupResponse {
  access_token: string
  token_type: string
}

export function signup(params: {
  email: string
  password: string
  full_name?: string
  workspace_name: string
}) {
  return apiClient.post<SignupResponse>('/auth/signup', params)
}

export interface StatusResponse {
  status: string
}

export function verifyEmail(token: string) {
  return apiClient.post<StatusResponse>('/auth/verify-email', { token })
}

export function resendVerification(email: string) {
  return apiClient.post<StatusResponse>('/auth/resend-verification', { email })
}

export function forgotPassword(email: string) {
  return apiClient.post<StatusResponse>('/auth/forgot-password', { email })
}

export function resetPassword(token: string, newPassword: string) {
  return apiClient.post<StatusResponse>('/auth/reset-password', {
    token,
    new_password: newPassword,
  })
}
