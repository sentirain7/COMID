import clsx from 'clsx'
import { CATEGORY_BADGE_STYLES } from '../../lib/constants'

function CategoryBadge({ category }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center justify-center w-20 px-1.5 py-0.5 rounded text-[10px] border font-medium overflow-hidden',
        CATEGORY_BADGE_STYLES[category] || 'bg-gray-500/20 text-gray-400 border-gray-500/30'
      )}
      title={category}
    >
      <span className="truncate capitalize">{category?.replace(/_/g, ' ')}</span>
    </span>
  )
}

export default CategoryBadge
