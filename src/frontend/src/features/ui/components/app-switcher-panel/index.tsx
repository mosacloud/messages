import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useConfig } from "@/features/providers/config";
import "./index.scss";

type AppId = "docs" | "drive" | "meet" | "mail" | "calendar" | "chat" | "commander" | "epicentre";

const APP_META: Record<AppId, { icon: string; label: string; subtitle: string; color: string; gradientEnd: string }> = {
  epicentre: { icon: "/images/icons/epicentre-icon.svg", label: "Epicentre", subtitle: "Home",        color: "#0284C7", gradientEnd: "#0443F2" },
  docs:      { icon: "/images/icons/file-icon.svg",      label: "Docs",      subtitle: "Documents",   color: "#06B6D4", gradientEnd: "#0891B2" },
  drive:     { icon: "/images/icons/folder-icon.svg",    label: "Drive",     subtitle: "Files",       color: "#F2AF05", gradientEnd: "#D97706" },
  meet:      { icon: "/images/icons/camera-icon.svg",    label: "Meet",      subtitle: "Video calls", color: "#00B574", gradientEnd: "#059669" },
  mail:      { icon: "/images/icons/mail-icon.svg",      label: "Mail",      subtitle: "Email",       color: "#F8497B", gradientEnd: "#A0033A" },
  calendar:  { icon: "/images/icons/calendar-icon.svg",  label: "Calendar",  subtitle: "Schedule",    color: "#A78BFA", gradientEnd: "#6D3FDE" },
  chat:      { icon: "/images/icons/chat-icon.svg",      label: "Chat",      subtitle: "Messaging",   color: "#FA7108", gradientEnd: "#C2410C" },
  commander: { icon: "/images/icons/commander-icon.svg", label: "Commander", subtitle: "Admin",       color: "#0284C7", gradientEnd: "#0064C8" },
};

const APP_ORDER: AppId[] = ["epicentre", "docs", "drive", "meet", "mail", "calendar", "chat", "commander"];

const AppIcon = ({ id, size = 40 }: { id: AppId; size?: number }) => {
  const { icon, label, color, gradientEnd } = APP_META[id];
  const radius = size <= 36 ? 9 : 12;
  return (
    <span
      className="app-switcher-panel__icon"
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        background: `linear-gradient(135deg, ${color} 0%, ${gradientEnd} 100%)`,
      }}
    >
      <img src={icon} alt={label} style={{ width: size * 0.45, height: size * 0.45 }} />
    </span>
  );
};

const Panel = ({ onClose, opensUpward }: { onClose: () => void; opensUpward: boolean }) => {
  const { APP_URLS } = useConfig();
  const { t } = useTranslation();

  const jumpTo = APP_ORDER.filter((id) => id !== "mail" && id in APP_URLS && id in APP_META);

  return (
    <div className={`app-switcher-panel__dropdown${opensUpward ? " app-switcher-panel__dropdown--up" : ""}`}>
      <div className="app-switcher-panel__current">
        <AppIcon id="mail" size={44} />
        <div className="app-switcher-panel__current-text">
          <span className="app-switcher-panel__you-are-in">{t("YOU'RE IN")}</span>
          <span className="app-switcher-panel__app-name">{t("Mail")}</span>
        </div>
      </div>

      {jumpTo.length > 0 && (
        <>
          <div className="app-switcher-panel__divider" />
          <span className="app-switcher-panel__section-label">{t("JUMP TO")}</span>
          <div className="app-switcher-panel__grid">
            {jumpTo.map((id) => {
              const { label, subtitle } = APP_META[id];
              return (
                <a
                  key={id}
                  href={APP_URLS[id]}
                  className="app-switcher-panel__app"
                  onClick={onClose}
                >
                  <AppIcon id={id} size={36} />
                  <div className="app-switcher-panel__app-info">
                    <span className="app-switcher-panel__app-label">{t(label)}</span>
                    <span className="app-switcher-panel__app-subtitle">{t(subtitle)}</span>
                  </div>
                </a>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
};

export const AppSwitcherButton = () => {
  const { APP_URLS } = useConfig();
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [opensUpward, setOpensUpward] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const hasOtherApps = APP_ORDER.some((id) => id !== "mail" && id in APP_URLS && id in APP_META);

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [isOpen]);

  if (!hasOtherApps) return null;

  const handleOpen = () => {
    if (ref.current) {
      const rect = ref.current.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      setOpensUpward(spaceBelow < 320);
    }
    setIsOpen((v) => !v);
  };

  return (
    <div ref={ref} className="app-switcher-panel">
      <Button
        color="brand"
        variant="tertiary"
        aria-label={t("Switch app")}
        aria-expanded={isOpen}
        onClick={handleOpen}
        icon={
          <span className="app-switcher-panel__trigger-grid" aria-hidden>
            {[...APP_ORDER, APP_ORDER[0]].map((id, i) => (
              <span key={i} style={{ background: APP_META[id].color }} />
            ))}
          </span>
        }
      />
      {isOpen && <Panel onClose={() => setIsOpen(false)} opensUpward={opensUpward} />}
    </div>
  );
};
