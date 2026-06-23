import clsx from 'clsx'
import { getRouteMeta } from '../../navigation/routeMeta'

function PageHeader({
  routeKey,
  subtitle,
  className,
  titleOverride,
  children,
}) {
  const meta = getRouteMeta(routeKey)
  const title = titleOverride || meta?.pageTitle || 'Page'

  return (
    <div className={clsx('flex items-center justify-between', className)}>
      <div>
        <h1 className="text-2xl font-bold text-white">{title}</h1>
        {subtitle ? <p className="text-slate-400 text-sm mt-1">{subtitle}</p> : null}
      </div>
      {children ? <div>{children}</div> : null}
    </div>
  )
}

export default PageHeader

