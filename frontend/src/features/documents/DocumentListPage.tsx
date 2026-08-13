import { useEffect, useState } from 'react'
import { FileText } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { listDocuments, type DocumentSummary } from './api/documentsApi'
import { DocumentViewerModal } from './components/DocumentViewerModal'

export function DocumentListPage() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [viewer, setViewer] = useState<{ id: string; title: string } | null>(null)

  useEffect(() => {
    listDocuments()
      .then(setDocuments)
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="mb-1 text-lg font-semibold">Documents</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Everything synchronized from Google Drive.
      </p>

      {loading && <p className="text-sm text-muted-foreground">Loading...</p>}

      <div className="space-y-2">
        {documents.map((doc) => (
          <Card
            key={doc.id}
            className="flex cursor-pointer items-center justify-between px-4 py-3 hover:border-primary/40"
            onClick={() => setViewer({ id: doc.id, title: doc.title })}
          >
            <div className="flex items-center gap-3">
              <FileText size={18} className="text-muted-foreground" />
              <div>
                <p className="text-sm font-medium">{doc.title}</p>
                <p className="text-xs text-muted-foreground">
                  Updated {new Date(doc.updated_at).toLocaleString()}
                </p>
              </div>
            </div>
            {doc.version_number && <Badge>v{doc.version_number}</Badge>}
          </Card>
        ))}
      </div>

      <DocumentViewerModal
        documentId={viewer?.id ?? null}
        title={viewer?.title ?? ''}
        onClose={() => setViewer(null)}
      />
    </div>
  )
}
