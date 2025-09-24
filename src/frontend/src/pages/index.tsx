import { useTranslation } from "react-i18next";
import { Hero, HomeGutter, Footer, ProConnectButton } from "@gouvfr-lasuite/ui-kit";
import { login, useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main";
import { LanguagePicker } from "@/features/layouts/components/main/language-picker";
import { AppLayout } from "@/features/layouts/components/main/layout";
import { LeftPanel } from "@/features/layouts/components/main/left-panel";
import { FeedbackWidget } from "@/features/ui/components/feedback-widget";

export default function HomePage() {

  const { t } = useTranslation();
  const { user } = useAuth();

  if (user) {
    return <MainLayout />;
  }


  return (
    <AppLayout
        hideLeftPanelOnDesktop
        leftPanelContent={<LeftPanel />}
        rightHeaderContent={<LanguagePicker />}
        icon={<img src="/images/app-logo.svg" alt="logo" height={32} />}
      >
      <div className="app__home">
        <HomeGutter>
          <Hero
            logo={<img src="/images/app-icon.svg" alt="Messages Logo" width={64} />}
            title={t("home.title")}
            banner="/images/banner.webp"
            subtitle={t("home.subtitle")}
            mainButton={<ProConnectButton onClick={login} />}
          />
        </HomeGutter>
        <Footer />
      </div>
      <FeedbackWidget />
      </AppLayout>
  );
}
