import { useCallback, useRef, useState } from 'react'

/**
 * Unified notification state management hook.
 *
 * @param {number} autoDismissMs - Auto-dismiss delay in ms (0 = no auto-dismiss). Default 5000.
 * @returns {{ notification: {type: string, message: string}|null, notify: Function, dismiss: Function }}
 */
export function useNotification(autoDismissMs = 5000) {
  const [notification, setNotification] = useState(null)
  const timerRef = useRef(null)

  const dismiss = useCallback(() => {
    clearTimeout(timerRef.current)
    setNotification(null)
  }, [])

  const notify = useCallback(
    (type, message) => {
      clearTimeout(timerRef.current)
      setNotification({ type, message })
      if (autoDismissMs > 0) {
        timerRef.current = setTimeout(() => setNotification(null), autoDismissMs)
      }
    },
    [autoDismissMs],
  )

  return { notification, notify, dismiss }
}
