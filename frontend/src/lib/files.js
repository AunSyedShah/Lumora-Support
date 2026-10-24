/* Attachment limits — the same ones the API applies, checked before upload. */
export const ALLOWED_FILES = ['.pdf', '.png', '.jpg', '.jpeg', '.txt']
export const MAX_FILES = 5
export const MAX_MB = 5

/** '' when the files are fine, otherwise a sentence explaining the problem. */
export function checkFiles(files) {
  if (files.length > MAX_FILES) return `You can attach up to ${MAX_FILES} files.`
  for (const f of files) {
    const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase()
    if (!ALLOWED_FILES.includes(ext)) return `${f.name}: only PDF, PNG, JPG and TXT files can be attached.`
    if (f.size > MAX_MB * 1024 * 1024) return `${f.name} is larger than ${MAX_MB} MB.`
  }
  return ''
}
