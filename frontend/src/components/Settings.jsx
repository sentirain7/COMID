import { useState, useEffect, useRef } from 'react'
import { Settings as SettingsIcon, RefreshCw, AlertCircle, CheckCircle, Atom } from 'lucide-react'
import { useSettings, useGPUStats } from '../hooks/useApi'
import { NotificationBanner } from './shared'
import { useNotification } from '../hooks/useNotification'
import { getActivePresetName, getActiveAnalysisBgName } from '../lib/colorPresets'

import LLMSection from './settings/LLMSection'
import GPUSection from './settings/GPUSection'
import NotificationSection from './settings/NotificationSection'
import ThemeSection from './settings/ThemeSection'
import {
  SUBMISSION_E_INTRA_METHOD_OPTIONS,
  getDefaultSubmissionEIntraMethod,
  getSubmissionEIntraMethodLabel,
} from '../lib/eIntraMethod'

function Settings() {
  const { settings, loading, error, update } = useSettings()
  const { data: gpuData } = useGPUStats(10000)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [activePreset, setActivePreset] = useState(getActivePresetName)
  const [activeAnalysisBg, setActiveAnalysisBg] = useState(getActiveAnalysisBgName)
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [modelInput, setModelInput] = useState(settings?.llm_model ?? '')
  const apiKeySubmittingRef = useRef(false)
  const { notification, notify, dismiss } = useNotification()

  useEffect(() => {
    if (error) notify('error', `Error loading settings: ${error}`)
  }, [error, notify])

  useEffect(() => {
    if (settings?.llm_model) {
      setModelInput(settings.llm_model)
    }
  }, [settings?.llm_model])

  const handleChange = async (key, value) => {
    setSaving(true)
    setSaveSuccess(false)
    try {
      await update({ [key]: value })
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2000)
    } catch (err) {
      console.error('Failed to save settings:', err)
    } finally {
      setSaving(false)
    }
  }

  const handleApiKeySubmit = async () => {
    const trimmed = apiKeyInput.trim()
    if (!trimmed || apiKeySubmittingRef.current) return
    apiKeySubmittingRef.current = true
    try {
      await update({ llm_api_key: trimmed, llm_provider: settings?.llm_provider })
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2000)
      setApiKeyInput('')
    } catch (err) {
      console.error('Failed to save API key:', err)
    } finally {
      apiKeySubmittingRef.current = false
    }
  }

  const handleModelSubmit = () => {
    const trimmed = modelInput.trim()
    if (!trimmed || trimmed === (settings?.llm_model ?? '')) return
    handleChange('llm_model', trimmed)
  }

  const handleGPUToggle = async (gpuId) => {
    const current = settings?.selected_gpus || []
    const newSelection = current.includes(gpuId)
      ? current.filter(id => id !== gpuId)
      : [...current, gpuId]
    await handleChange('selected_gpus', newSelection)
  }

  if (loading && !settings) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-slate-700 rounded-lg flex items-center justify-center">
            <SettingsIcon className="w-5 h-5 text-slate-300" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Settings</h1>
            <p className="text-slate-400 text-sm mt-1">
              Configure simulation and dashboard preferences.
            </p>
          </div>
        </div>
        {saveSuccess && (
          <div className="flex items-center gap-2 text-green-400">
            <CheckCircle className="w-4 h-4" />
            <span className="text-sm">Saved</span>
          </div>
        )}
      </div>

      <NotificationBanner notification={notification} onDismiss={dismiss} />

      <LLMSection
        settings={settings}
        saving={saving}
        handleChange={handleChange}
        apiKeyInput={apiKeyInput}
        setApiKeyInput={setApiKeyInput}
        handleApiKeySubmit={handleApiKeySubmit}
        modelInput={modelInput}
        setModelInput={setModelInput}
        handleModelSubmit={handleModelSubmit}
      />

      <GPUSection
        settings={settings}
        gpuData={gpuData}
        saving={saving}
        handleChange={handleChange}
        handleGPUToggle={handleGPUToggle}
      />

      <NotificationSection
        settings={settings}
        saving={saving}
        handleChange={handleChange}
      />

      <section className="card">
        <div className="card-header flex items-center gap-2">
          <Atom className="w-5 h-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-white">E_intra Defaults</h2>
        </div>
        <div className="card-body space-y-4">
          <div className="flex items-start justify-between gap-6">
            <div className="flex-1">
              <label className="text-white font-medium">Default E_intra Method</label>
              <p className="text-sm text-slate-400 mt-1">
                Default for new submissions only. Molecules coverage and ML serving keep their own stored method policies.
              </p>
            </div>
            <select
              className="input w-56"
              value={getDefaultSubmissionEIntraMethod(settings?.default_e_intra_method)}
              onChange={(e) => handleChange('default_e_intra_method', e.target.value)}
              disabled={saving}
              aria-label="Default E_intra Method"
            >
              {SUBMISSION_E_INTRA_METHOD_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <p className="text-xs text-slate-500">
            Current default: {getSubmissionEIntraMethodLabel(settings?.default_e_intra_method)}
          </p>
        </div>
      </section>

      <ThemeSection
        activePreset={activePreset}
        setActivePreset={setActivePreset}
        activeAnalysisBg={activeAnalysisBg}
        setActiveAnalysisBg={setActiveAnalysisBg}
      />

      {/* Info Note */}
      <div className="card p-4 bg-blue-500/10 border-blue-500/30">
        <div className="flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="font-medium text-blue-400">Session Settings</h3>
            <p className="text-sm text-slate-300 mt-1">
              Most settings are stored in settings.json and persist across page reloads.
              The default E_intra method is also persisted in settings.json for new submissions.
              LLM settings take effect immediately.
              Environment variables (LLM_*) override these values on server restart.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Settings
