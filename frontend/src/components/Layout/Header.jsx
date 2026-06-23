import { Link } from "react-router-dom";
import { Bell, Settings, Cpu, HardDrive } from "lucide-react";
import { useHealth, useSystemStats } from "../../hooks/useApi";
import NacmidIcon from "../icons/NacmidIcon";
import NacmidLogotype from "../icons/NacmidLogotype";

const healthDotClass = (status) => {
  if (status === "ready") return "bg-green-400";
  if (status === "limited") return "bg-yellow-400";
  return "bg-red-400";
};

const COMPONENT_LABELS = {
  database: "DB",
  redis: "Redis",
  celery_workers: "Worker",
};

function Header() {
  const { data: health, loading } = useHealth();
  const { data: systemStats } = useSystemStats();

  const healthComponents = health?.components || {};
  const componentOrder = ["database", "redis", "celery_workers"];

  return (
    <header className="fixed top-0 left-0 right-0 h-16 bg-[#111827] border-b border-[#1f2937] z-50 shadow-lg shadow-black/20">
      <div className="flex items-center justify-between h-full px-6">
        {/* Logo - KICT CI Style */}
        <div className="flex items-center gap-3">
          {/* Icon - same height as the acronym + full name */}
          <NacmidIcon className="w-11 h-11 flex-shrink-0" />

          {/* Acronym + full name stacked vertically, left-aligned */}
          <div className="flex flex-col justify-center items-start">
            <NacmidLogotype className="h-7" />
            {/* Full name */}
            <p className="text-[9px] text-slate-400 tracking-wide -mt-0.5 font-medium">
              AI-Driven Computational Platform for Nanoscale Construction Material Inverse Design
            </p>
          </div>
        </div>

        {/* Status */}
        <div className="flex items-center gap-6">
          {/* System Resources */}
          <div className="flex items-center gap-4 text-xs border-r border-slate-700 pr-4 mr-2">
            <div className="flex items-center gap-1.5" title="CPU usage">
              <Cpu className="w-3.5 h-3.5 text-slate-400" />
              <span className="text-slate-300 font-mono">
                {systemStats?.cpu_percent?.toFixed(0) ?? "-"}%
              </span>
            </div>
            <div className="flex items-center gap-1.5" title="Memory usage">
              <HardDrive className="w-3.5 h-3.5 text-slate-400" />
              <span className="text-slate-300 font-mono">
                {systemStats?.memory_percent?.toFixed(0) ?? "-"}%
              </span>
            </div>
          </div>

          {/* Service Health — compact component dots */}
          <div className="flex items-center gap-2">
            {componentOrder.map((name) => {
              const c = healthComponents?.[name];
              const label = COMPONENT_LABELS[name] || name;
              const latency =
                c && Number.isFinite(c.latency_ms)
                  ? `${c.latency_ms.toFixed(0)}ms`
                  : "-";
              return (
                <span
                  key={name}
                  className="flex items-center gap-1 text-[11px] text-slate-400"
                  title={`${label}: ${c?.status || "?"} (${latency})`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${loading ? "bg-yellow-400 animate-pulse" : healthDotClass(c?.status)}`}
                  />
                  {label}
                </span>
              );
            })}
          </div>

          {/* Version */}
          <div className="text-[11px] text-slate-500">
            v{health?.version || "-"}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button className="p-2 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors">
              <Bell className="w-5 h-5" />
            </button>
            <Link
              to="/settings"
              className="p-2 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors"
            >
              <Settings className="w-5 h-5" />
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}

export default Header;
