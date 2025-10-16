import { MainLayout } from "@/features/layouts/components/main";
import { useEffect } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import { useMailboxContext } from "@/features/providers/mailbox";
import { ManageMessageTemplatesViewPageContent } from "@/features/layouts/components/mailbox-settings/message-templates-view/page-content";
import { ComposeTemplateAction } from "@/features/layouts/components/mailbox-settings/message-templates-view/compose-template-action";

const MailboxMessageTemplatesPage = () => {
    const { t } = useTranslation();
    const router = useRouter();
    const { queryStates, selectedMailbox } = useMailboxContext();

    useEffect(() => {
        if (!queryStates.mailboxes.isLoading && !selectedMailbox) {
            router.push("/");
        }
    }, [queryStates.mailboxes.isLoading, selectedMailbox, router]);

    return (
        <div className="admin-page">
            <div className="admin-page__header">
                <h1 className="title">{t("Message templates")}</h1>
                <div className="admin-page__actions">
                    <ComposeTemplateAction />
                </div>
            </div>

            <div className="admin-page__content">
                {selectedMailbox && <ManageMessageTemplatesViewPageContent />}
            </div>
        </div>
    );
}

MailboxMessageTemplatesPage.getLayout = (page: React.ReactElement) => {
    return <MainLayout>{page}</MainLayout>;
};

export default MailboxMessageTemplatesPage;
