import { Navigate, Route, Routes } from 'react-router-dom'
import { LoginPage } from '@/features/auth/LoginPage'
import { ChatPage } from '@/features/chat/ChatPage'
import { DocumentListPage } from '@/features/documents/DocumentListPage'
import { RequireVerified } from './guards'
import { AppShell } from './AppShell'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
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
