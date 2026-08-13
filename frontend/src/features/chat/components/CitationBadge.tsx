import { FileText } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { Citation } from '../api/chatApi'

interface CitationBadgeProps {
  citation: Citation
  index: number
  onOpen: (documentId: string, title: string) => void
}

export function CitationBadge({ citation, index, onOpen }: CitationBadgeProps) {
  return (
    <button
      onClick={() => onOpen(citation.document_id, citation.document_title)}
      className="group"
      title={citation.chunk_text_snippet}
    >
      <Badge className="gap-1 transition-colors group-hover:border-primary/50 group-hover:text-foreground">
        <FileText size={12} />
        [{index + 1}] {citation.document_title}
        <span className="text-muted-foreground">v{citation.version_number}</span>
      </Badge>
    </button>
  )
}
