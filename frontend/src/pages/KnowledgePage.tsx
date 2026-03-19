import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  BookOpen,
  Search,
  Upload,
  Plus,
  FileText,
  Tag,
  Server,
  X,
  Loader2,
  ChevronRight,
} from 'lucide-react'
import { cn, formatRelativeTime } from '@/lib/utils'
import { searchKnowledge, ingestKnowledge, listKnowledgeDocs, type KnowledgeDocument } from '@/lib/api'

type DocType = 'runbook' | 'postmortem' | 'doc'

function DocTypeTag({ type }: { type: string }) {
  const styles: Record<string, string> = {
    runbook: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
    postmortem: 'text-red-400 bg-red-500/10 border-red-500/20',
    incident: 'text-orange-400 bg-orange-500/10 border-orange-500/20',
    doc: 'text-gray-400 bg-gray-500/10 border-gray-500/20',
  }
  return (
    <span className={cn('inline-flex items-center px-2 py-0.5 rounded border text-xs font-medium', styles[type] ?? styles.doc)}>
      {type}
    </span>
  )
}

function DocCard({ doc, selected, onClick }: { doc: KnowledgeDocument; selected: boolean; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'flex items-start gap-3 p-3 rounded-xl cursor-pointer border transition-all',
        selected
          ? 'bg-indigo-600/10 border-indigo-500/30'
          : 'bg-gray-900 border-gray-800 hover:border-gray-600'
      )}
    >
      <FileText size={16} className="text-gray-500 mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-gray-100 truncate">{doc.title}</span>
          <DocTypeTag type={doc.type} />
        </div>
        {doc.services.length > 0 && (
          <div className="flex items-center gap-1 mt-1">
            <Server size={11} className="text-gray-600" />
            <span className="text-xs text-gray-500">{doc.services.slice(0, 3).join(', ')}</span>
          </div>
        )}
        <div className="flex items-center gap-2 mt-1">
          {doc.tags.slice(0, 3).map((tag) => (
            <span key={tag} className="flex items-center gap-0.5 text-xs text-gray-600">
              <Tag size={9} />
              {tag}
            </span>
          ))}
          <span className="ml-auto text-xs text-gray-600">{formatRelativeTime(doc.created_at)}</span>
        </div>
      </div>
      <ChevronRight size={14} className="text-gray-600 mt-0.5 shrink-0" />
    </div>
  )
}

interface IngestFormProps {
  onClose: () => void
}

function IngestForm({ onClose }: IngestFormProps) {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [type, setType] = useState<DocType>('runbook')
  const [services, setServices] = useState('')
  const [tags, setTags] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const qc = useQueryClient()
  const ingest = useMutation({
    mutationFn: ingestKnowledge,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['knowledge', 'list'] })
      onClose()
    },
  })

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setTitle(file.name.replace(/\.[^.]+$/, ''))
    const reader = new FileReader()
    reader.onload = (ev) => setContent(ev.target?.result as string)
    reader.readAsText(file)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    ingest.mutate({
      title,
      content,
      type,
      services: services.split(',').map((s) => s.trim()).filter(Boolean),
      tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
    })
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h2 className="text-base font-semibold text-gray-100">Ingest Document</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* File upload */}
          <div>
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="flex items-center gap-2 px-4 py-2 border border-dashed border-gray-600 rounded-lg text-sm text-gray-400 hover:border-indigo-500 hover:text-indigo-400 transition-colors w-full justify-center"
            >
              <Upload size={15} />
              Upload file (Markdown, text)
            </button>
            <input ref={fileRef} type="file" accept=".md,.txt,.markdown" className="hidden" onChange={handleFileUpload} />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Title *</label>
            <input
              required
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Checkout Service Runbook"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 outline-none focus:border-indigo-500/50"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Type</label>
            <div className="flex gap-2">
              {(['runbook', 'postmortem', 'doc'] as DocType[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setType(t)}
                  className={cn(
                    'flex-1 py-1.5 rounded-lg text-xs font-medium border transition-colors capitalize',
                    type === t
                      ? 'bg-indigo-600/20 border-indigo-500 text-indigo-300'
                      : 'bg-gray-800 border-gray-700 text-gray-500 hover:text-gray-300'
                  )}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Content *</label>
            <textarea
              required
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={10}
              placeholder="Paste or type the runbook / post-mortem content here..."
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 outline-none focus:border-indigo-500/50 resize-none font-mono"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Services (comma separated)</label>
            <input
              type="text"
              value={services}
              onChange={(e) => setServices(e.target.value)}
              placeholder="checkout, payment, orders"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 outline-none focus:border-indigo-500/50"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Tags (comma separated)</label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="database, latency, outage"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600 outline-none focus:border-indigo-500/50"
            />
          </div>

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 py-2 rounded-lg border border-gray-700 text-sm text-gray-400 hover:text-gray-200 transition-colors">
              Cancel
            </button>
            <button
              type="submit"
              disabled={!title || !content || ingest.isPending}
              className="flex-1 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {ingest.isPending ? (
                <><Loader2 size={14} className="animate-spin" /> Ingesting...</>
              ) : (
                <><Upload size={14} /> Ingest Document</>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function KnowledgePage() {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedDoc, setSelectedDoc] = useState<KnowledgeDocument | null>(null)
  const [showIngest, setShowIngest] = useState(false)
  const [debouncedSearch, setDebouncedSearch] = useState('')

  const { data: docs, isLoading: docsLoading } = useQuery<KnowledgeDocument[]>({
    queryKey: ['knowledge', 'list'],
    queryFn: () => listKnowledgeDocs(),
  })

  const { data: searchResults, isLoading: searchLoading } = useQuery({
    queryKey: ['knowledge', 'search', debouncedSearch],
    queryFn: () => searchKnowledge(debouncedSearch, 20),
    enabled: debouncedSearch.length > 2,
  })

  const handleSearchChange = (q: string) => {
    setSearchQuery(q)
    const t = setTimeout(() => setDebouncedSearch(q), 400)
    return () => clearTimeout(t)
  }

  const isSearching = debouncedSearch.length > 2
  const displayDocs: KnowledgeDocument[] = isSearching
    ? (searchResults?.map((r) => r.document) ?? [])
    : (docs ?? [])

  const isLoading = isSearching ? searchLoading : docsLoading

  return (
    <div className="flex flex-col h-full gap-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <BookOpen size={20} className="text-blue-400" />
            Knowledge Base
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            RAPTOR — Recursive Abstractive Processing for Tree-Organized Retrieval
          </p>
        </div>
        <button
          onClick={() => setShowIngest(true)}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Plus size={15} />
          Ingest Document
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => handleSearchChange(e.target.value)}
          placeholder="Search runbooks, post-mortems, incident reports... (RAG-powered)"
          className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 pl-10 text-sm text-gray-200 placeholder:text-gray-600 outline-none focus:border-indigo-500/50"
        />
        {searchLoading && (
          <Loader2 size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 animate-spin" />
        )}
      </div>

      {/* Search results header */}
      {isSearching && searchResults && (
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <Search size={12} />
          Found {searchResults.length} results for "{debouncedSearch}"
        </div>
      )}

      {/* Main content */}
      <div className="flex gap-5 flex-1 min-h-0">
        {/* Doc list */}
        <div className="flex-1 overflow-y-auto space-y-2 min-h-0">
          {isLoading && (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-20 bg-gray-900 rounded-xl border border-gray-800 animate-pulse" />
              ))}
            </div>
          )}

          {!isLoading && displayDocs.length === 0 && (
            <div className="flex flex-col items-center justify-center h-48 text-gray-600 gap-2">
              <BookOpen size={32} />
              <p className="text-sm">{isSearching ? 'No documents match your search' : 'No documents yet'}</p>
              {!isSearching && (
                <button
                  onClick={() => setShowIngest(true)}
                  className="text-xs text-indigo-400 hover:text-indigo-300 mt-1"
                >
                  Ingest your first document →
                </button>
              )}
            </div>
          )}

          {!isLoading && displayDocs.map((doc) => (
            <DocCard
              key={doc.id}
              doc={doc}
              selected={selectedDoc?.id === doc.id}
              onClick={() => setSelectedDoc(selectedDoc?.id === doc.id ? null : doc)}
            />
          ))}
        </div>

        {/* Doc detail panel */}
        {selectedDoc && (
          <div className="w-96 shrink-0 flex flex-col bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
              <div className="flex items-center gap-2">
                <FileText size={15} className="text-gray-400" />
                <span className="text-sm font-semibold text-gray-200 truncate">{selectedDoc.title}</span>
              </div>
              <button
                onClick={() => setSelectedDoc(null)}
                className="text-gray-600 hover:text-gray-400"
              >
                <X size={15} />
              </button>
            </div>

            <div className="p-4 border-b border-gray-800 flex flex-wrap gap-2">
              <DocTypeTag type={selectedDoc.type} />
              {selectedDoc.services.map((svc) => (
                <span key={svc} className="flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-400 border border-gray-700">
                  <Server size={10} />
                  {svc}
                </span>
              ))}
              {selectedDoc.tags.map((tag) => (
                <span key={tag} className="flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-500">
                  <Tag size={10} />
                  {tag}
                </span>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              <div className="prose prose-sm prose-invert max-w-none">
                <ReactMarkdownContent content={selectedDoc.content} />
              </div>
            </div>
          </div>
        )}
      </div>

      {showIngest && <IngestForm onClose={() => setShowIngest(false)} />}
    </div>
  )
}

// Inline wrapper to avoid importing ReactMarkdown at top level before it's needed
function ReactMarkdownContent({ content }: { content: string }) {
  // Simple text rendering as fallback (avoid circular import)
  return (
    <pre className="whitespace-pre-wrap text-xs text-gray-300 font-mono leading-relaxed">
      {content}
    </pre>
  )
}
