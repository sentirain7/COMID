import { useEffect, useRef, useState } from 'react'
import { useSettings } from './useApi'
import { getDefaultSubmissionEIntraMethod } from '../lib/eIntraMethod'

export function useSubmissionEIntraMethod() {
  const { settings } = useSettings()
  const defaultEIntraMethod = getDefaultSubmissionEIntraMethod(
    settings?.default_e_intra_method,
  )
  const previousDefaultRef = useRef(defaultEIntraMethod)
  const [selectedEIntraMethod, setSelectedEIntraMethod] = useState(defaultEIntraMethod)

  useEffect(() => {
    setSelectedEIntraMethod((current) => {
      if (!current || current === previousDefaultRef.current) {
        return defaultEIntraMethod
      }
      return current
    })
    previousDefaultRef.current = defaultEIntraMethod
  }, [defaultEIntraMethod])

  return {
    settings,
    defaultEIntraMethod,
    effectiveEIntraMethod: selectedEIntraMethod || defaultEIntraMethod,
    selectedEIntraMethod,
    setSelectedEIntraMethod,
  }
}
