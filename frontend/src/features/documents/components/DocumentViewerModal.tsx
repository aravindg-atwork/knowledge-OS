import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/apiClient'

interface DocumentViewerModalProps {
  documentId: string | null
  title: string
  onClose: () => void
}

export function DocumentViewerModal({ documentId, title, onClose }: DocumentViewerModalProps) {
  const [blob, setBlob] = useState<Blob | null>(null)
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [textContent, setTextContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!documentId) return
    setLoading(true)
    setBlob(null)
    setTextContent(null)

    apiClient
      .get<Blob>(`/documents/${documentId}/content`)
      .then(async (data) => {
        setBlob(data)
        if (data.type.startsWith('text/') || data.type.includes('html')) {
          setTextContent(await data.text())
        }
      })
      .finally(() => setLoading(false))

    return () => {
      setObjectUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev)
        return null
      })
    }
  }, [documentId])

  useEffect(() => {
    if (blob && (blob.type === 'application/pdf' || blob.type.includes('html'))) {
      const url = URL.createObjectURL(blob)
      setObjectUrl(url)
      return () => URL.revokeObjectURL(url)
    }
  }, [blob])

  function handleDownload() {
    if (!blob || !documentId) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = title
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Dialog open={documentId !== null} onClose={onClose} title={title}>
      {loading && <p className="text-sm text-muted-foreground">Loading document...</p>}

      {!loading && textContent && !blob?.type.includes('html') && (
        <pre className="whitespace-pre-wrap text-sm">{textContent}</pre>
      )}

      {!loading && blob?.type === 'application/pdf' && objectUrl && (
        <iframe src={objectUrl} title={title} className="h-[60vh] w-full rounded-md border border-border" />
      )}

      {!loading && blob?.type.includes('html') && objectUrl && (
        <iframe src={objectUrl} title={title} className="h-[60vh] w-full rounded-md border border-border bg-white" />
      )}

      {!loading && blob && !textContent && blob.type !== 'application/pdf' && !blob.type.includes('html') && (
        <div className="flex flex-col items-center gap-3 py-6 text-sm text-muted-foreground">
          <p>Preview isn't available for this file type ({blob.type || 'unknown'}).</p>
          <Button variant="outline" onClick={handleDownload}>
            <Download size={14} /> Download original
          </Button>
        </div>
      )}
    </Dialog>
  )
}
