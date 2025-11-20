import { useTranslation } from "react-i18next";
import { Hero, HomeGutter, Footer } from "@gouvfr-lasuite/ui-kit";
import { login, useAuth } from "@/features/auth";
import { MainLayout } from "@/features/layouts/components/main";
import { LanguagePicker } from "@/features/layouts/components/main/language-picker";
import { AppLayout } from "@/features/layouts/components/main/layout";
import { LeftPanel } from "@/features/layouts/components/main/left-panel";
import { FeedbackWidget } from "@/features/ui/components/feedback-widget";
import { Button } from "@openfun/cunningham-react";

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
            title={t("Simple and intuitive messaging")}
            banner="/images/banner.webp"
            subtitle={t("Send and receive your messages in an instant.")}
            mainButton={<Button onClick={login}>
              {t("Get started")}
            </Button>}
          />
        </HomeGutter>
        <Footer />
      </div>
      <FeedbackWidget />
      </AppLayout>
  );
}
