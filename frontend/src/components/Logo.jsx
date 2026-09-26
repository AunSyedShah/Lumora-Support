export default function Logo({ size = 'md', onDark = false }) {
  const circle = size === 'sm' ? 'size-9 text-[17px]' : 'size-11 text-xl'
  return (
    <div
      aria-hidden="true"
      className={`${circle} flex shrink-0 items-center justify-center rounded-full font-display font-bold ${onDark ? 'bg-sun text-forest' : 'bg-forest text-sun'}`}
    >
      L
    </div>
  )
}
