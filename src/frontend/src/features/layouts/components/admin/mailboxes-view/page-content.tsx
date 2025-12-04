import { useTranslation } from "react-i18next";
import { usePagination } from "@gouvfr-lasuite/cunningham-react";
import { Icon, IconType, Spinner } from "@gouvfr-lasuite/ui-kit";
import { useAdminMailDomain } from "@/features/providers/admin-maildomain";
import { AdminMailboxDataGrid } from "./mailbox-data-grid";
import { Banner } from "@/features/ui/components/banner";

type AdminDomainPageContentProps = {
    pagination: ReturnType<typeof usePagination>;
}

export const AdminDomainPageContent = ({ pagination }: AdminDomainPageContentProps) => {
    const { t } = useTranslation();
    const { selectedMailDomain, isLoading } = useAdminMailDomain();

    if (isLoading) {
      return (
          <div className="admin-page__loading">
            <Spinner />
          </div>
      )
    }

    if (!selectedMailDomain) {
      return (
          <Banner type="error" icon={<Icon name="search_off" type={IconType.OUTLINED} />}>
            {t("Domain not found")}
          </Banner>
      );
    }

    return <AdminMailboxDataGrid domain={selectedMailDomain} pagination={pagination} />;
  }
