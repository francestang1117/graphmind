import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './styles/index.css'
import App from './App.tsx'
import { AUTH_SESSION_CHANGED_EVENT } from './services/authSession'

// React Query is already here for graph/search; uploads keep their own flow
// because file transfer and job progress are easier to reason about together.
const queryClient = new QueryClient()

const isPrivateQuery = (query: { queryKey: readonly unknown[] }) => {
  const rootKey = query.queryKey[0]
  return rootKey !== 'disease-guide' && rootKey !== 'disease-guide-search'
}

window.addEventListener(AUTH_SESSION_CHANGED_EVENT, () => {
  void queryClient.cancelQueries({ predicate: isPrivateQuery }).then(() => {
    queryClient.removeQueries({ predicate: isPrivateQuery })
  })
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
