import { Brain } from 'lucide-react'

function LLMSection({
  settings,
  saving,
  handleChange,
  apiKeyInput,
  setApiKeyInput,
  handleApiKeySubmit,
  modelInput,
  setModelInput,
  handleModelSubmit,
}) {
  return (
    <section className="card">
      <div className="card-header flex items-center gap-2">
        <Brain className="w-5 h-5 text-slate-400" />
        <h2 className="text-lg font-semibold text-white">LLM Provider</h2>
      </div>
      <div className="card-body space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <label className="text-white font-medium">LLM Provider</label>
            <p className="text-sm text-slate-400 mt-1">
              Provider for LLM-assisted features (mock = keyword fallback)
            </p>
          </div>
          <select
            className="input w-28"
            value={settings?.llm_provider ?? 'mock'}
            onChange={(e) => handleChange('llm_provider', e.target.value)}
            disabled={saving}
          >
            <option value="mock">Mock</option>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>

        {(settings?.llm_provider === 'openai' || settings?.llm_provider === 'anthropic') && (
          <>
            <div className="flex items-center justify-between gap-4">
              <div className="flex-1">
                <label className="text-white font-medium">API Key</label>
                <p className="text-sm text-slate-400 mt-1">
                  {settings.llm_provider === 'openai' ? 'OpenAI' : 'Anthropic'} API key (stored locally in settings.json)
                </p>
              </div>
              <input
                type="password"
                className="input w-64 py-2 px-2 text-sm"
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
                onBlur={handleApiKeySubmit}
                onKeyDown={(e) => e.key === 'Enter' && handleApiKeySubmit()}
                disabled={saving}
                placeholder={settings?.llm_api_key ? 'Configured (saved)' : 'sk-...'}
              />
            </div>

            <div className="flex items-center justify-between gap-4">
              <div className="flex-1">
                <label className="text-white font-medium">Model</label>
                <p className="text-sm text-slate-400 mt-1">
                  Leave empty for default ({settings.llm_provider === 'openai' ? 'gpt-4o-mini' : 'claude-3-5-sonnet-latest'})
                </p>
              </div>
              <input
                className="input w-48 py-2 px-2 text-sm"
                value={modelInput}
                onChange={(e) => setModelInput(e.target.value)}
                onBlur={handleModelSubmit}
                onKeyDown={(e) => e.key === 'Enter' && handleModelSubmit()}
                disabled={saving}
                placeholder={settings.llm_provider === 'openai' ? 'gpt-4o-mini' : 'claude-3-5-sonnet-latest'}
              />
            </div>
          </>
        )}
      </div>
    </section>
  )
}

export default LLMSection
