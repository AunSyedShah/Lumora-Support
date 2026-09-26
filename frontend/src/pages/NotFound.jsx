import { Button, EmptyState } from '../components/ui'

export default function NotFound({ title = 'Page not found' }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-6 p-10">
      <EmptyState title={title}>This page doesn’t exist — it may have moved.</EmptyState>
      <Button variant="outline" to="/">
        Go to my start page
      </Button>
    </div>
  )
}
