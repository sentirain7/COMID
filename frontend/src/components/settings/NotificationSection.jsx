import { RefreshCw } from 'lucide-react'

function NotificationSection({ settings, saving, handleChange }) {
  return (
    <>
      {/* Refresh Intervals */}
      <section className="card">
        <div className="card-header flex items-center gap-2">
          <RefreshCw className="w-5 h-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-white">Refresh Intervals</h2>
        </div>
        <div className="card-body space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium">Queue Stats Refresh</label>
              <p className="text-sm text-slate-400 mt-1">
                How often to update queue statistics
              </p>
            </div>
            <select
              className="input w-28"
              value={settings?.refresh_interval_queue_ms ?? 3000}
              onChange={(e) => handleChange('refresh_interval_queue_ms', parseInt(e.target.value))}
              disabled={saving}
            >
              <option value={1000}>1 second</option>
              <option value={3000}>3 seconds</option>
              <option value={5000}>5 seconds</option>
              <option value={10000}>10 seconds</option>
            </select>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium">GPU Stats Refresh</label>
              <p className="text-sm text-slate-400 mt-1">
                How often to update GPU utilization
              </p>
            </div>
            <select
              className="input w-28"
              value={settings?.refresh_interval_gpu_ms ?? 3000}
              onChange={(e) => handleChange('refresh_interval_gpu_ms', parseInt(e.target.value))}
              disabled={saving}
            >
              <option value={1000}>1 second</option>
              <option value={3000}>3 seconds</option>
              <option value={5000}>5 seconds</option>
              <option value={10000}>10 seconds</option>
            </select>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <label className="text-white font-medium">System Stats Refresh</label>
              <p className="text-sm text-slate-400 mt-1">
                How often to update CPU/Memory usage
              </p>
            </div>
            <select
              className="input w-28"
              value={settings?.refresh_interval_system_ms ?? 5000}
              onChange={(e) => handleChange('refresh_interval_system_ms', parseInt(e.target.value))}
              disabled={saving}
            >
              <option value={3000}>3 seconds</option>
              <option value={5000}>5 seconds</option>
              <option value={10000}>10 seconds</option>
              <option value={30000}>30 seconds</option>
            </select>
          </div>
        </div>
      </section>
    </>
  )
}

export default NotificationSection
