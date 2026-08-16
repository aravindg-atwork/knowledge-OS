import { Navigate, Route, Routes } from 'react-router-dom'
import { LoginPage } from '@/features/auth/LoginPage'
import { SignupPage } from '@/features/auth/SignupPage'
import { VerifyEmailPage } from '@/features/auth/VerifyEmailPage'
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage'
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage'
import { AcceptInvitePage } from '@/features/invites/AcceptInvitePage'
import { ChatPage } from '@/features/chat/ChatPage'
import { DocumentListPage } from '@/features/documents/DocumentListPage'
import { RequireVerified } from './guards'
import { AppShell } from './AppShell'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/invite/accept" element={<AcceptInvitePage />} />
      <Route
        path="/"
        element={
          <RequireVerified>
            <AppShell />
          </RequireVerified>
        }
      >
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="documents" element={<DocumentListPage />} />
      </Route>
    </Routes>
  )
}
