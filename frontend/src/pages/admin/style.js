/** Small inputs shared by the settings screens. */
export const input = 'rounded-xl border-[1.5px] border-line bg-white px-3 py-2 text-[15px] text-ink focus:border-forest focus:outline-none'
export const fieldLabel = 'flex flex-col gap-1 text-[13px] text-muted'

/** "Smart plug overheating" -> "SMART_PLUG_OVERHEATING" (codes are kept out of sight). */
export const codeFrom = (name) =>
  name
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 50)
