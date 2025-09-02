import { AppLayout } from "@/features/layouts/components/main/layout";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { AdminMailDomainProvider, useAdminMailDomain } from "@/features/providers/admin-maildomain";
import useAbility, { Abilities } from "@/hooks/use-ability";
import ErrorPage from "next/error";
import { Toaster } from "@/features/ui/components/toaster";

type AdminLayoutProps = {
  children: React.ReactNode;
  currentTab?: string;
  actions?: React.ReactNode;
};

function AdminLayoutContent({
  children,
  currentTab,
  actions
}: AdminLayoutProps) {
  const { t } = useTranslation();
  const { selectedMailDomain } = useAdminMailDomain();
  const canViewDomainAdmin = useAbility(Abilities.CAN_VIEW_DOMAIN_ADMIN);

  // Build breadcrumb items
  const breadcrumbItems = [
    {
      content: (
        <Link href="/" className="c__breadcrumbs__button" title={t("admin_layout.breadcrumbs.back")}>
          <span className="material-icons">mail</span>
        </Link>
      )
    },
    {
      content: (
        <Link href="/domain" className="c__breadcrumbs__button">
          {t("admin_layout.breadcrumbs.maildomains_management")}
        </Link>
      )
    }
  ];

  if (selectedMailDomain) {
    breadcrumbItems.push({
      content: (
        <Link href={`/domain/${selectedMailDomain.id}`} className="c__breadcrumbs__button">
          {selectedMailDomain.name || selectedMailDomain.id}
        </Link>
      )
    });

    // Add current page to breadcrumbs if not on main addresses page
    if (currentTab && currentTab !== "addresses") {
      const tabLabels = {
        dns: t("admin_layout.tabs.dns"),
        signatures: t("admin_layout.tabs.signatures")
      };
      breadcrumbItems.push({
        content: (
          <span className="c__breadcrumbs__button active">
            {tabLabels[currentTab as keyof typeof tabLabels]}
          </span>
        )
      });
    }
  }

  // Build tabs if we're in a domain
  const tabs = selectedMailDomain ? [
    { id: "addresses", label: t("admin_layout.tabs.addresses"), href: `/domain/${selectedMailDomain.id}` },
    { id: "dns", label: t("admin_layout.tabs.dns"), href: `/domain/${selectedMailDomain.id}/dns` },
    // { id: "signatures", label: t("admin_layout.tabs.signatures"), href: `/domain/${selectedMailDomain.id}/signatures` },
  ] : [];

  if (!canViewDomainAdmin) {
    return <ErrorPage statusCode={403} />;
  }

  return (
    <div className="admin-page">
      <div className="admin-page__header">
        <div className="admin-page__breadcrumbs">
          <Breadcrumbs items={breadcrumbItems} />
        </div>

        {actions && (
          <div className="admin-page__actions">
            {actions}
          </div>
        )}
      </div>

      {tabs.length > 0 && (
        <div className="admin-page__tabs">
          {tabs.map((tab) => (
            <Link
              key={tab.id}
              href={tab.href}
              className={`admin-page__tab ${currentTab === tab.id ? "admin-page__tab--active" : ""}`}
            >
              {tab.label}
            </Link>
          ))}
        </div>
      )}

      <div className="admin-page__content">
        {children}
      </div>
    </div>
  );
}

export function AdminLayout(props: AdminLayoutProps) {
  return (
      <AppLayout
        isLeftPanelOpen={false}
        setIsLeftPanelOpen={() => {}}
        leftPanelContent={null}
        hideSearch
        hideLeftPanelOnDesktop={true}
        icon={<Link href="/"><img src="/images/app-logo.svg" alt="logo" height={32} /></Link>}
      >
        <AdminMailDomainProvider>
          <AdminLayoutContent {...props} />
          <Toaster />
        </AdminMailDomainProvider>
      </AppLayout>
  );
}
