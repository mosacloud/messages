import { MainLayout } from "@/features/layouts/components/main";
import { useResponsive } from "@gouvfr-lasuite/ui-kit";
import { ThreadPanel } from "@/features/layouts/components/thread-panel";
import { ThreadSelectionPlaceholder } from "@/features/layouts/components/thread-selection-placeholder";
import { ThreadViewEmpty } from "@/features/layouts/components/thread-view/components/thread-view-empty";
import { ThreadSelectionProvider, useThreadSelection } from "@/features/providers/thread-selection";
import { useTranslation } from "react-i18next";
import { Panel, Group, Separator, useDefaultLayout } from "react-resizable-panels";
import { useMailboxContext } from "@/features/providers/mailbox";
import useAbility, { Abilities } from "@/hooks/use-ability";
import { useMemo } from "react";
import ViewHelper from "@/features/utils/view-helper";
import { useSearchParams } from "next/navigation";

const Mailbox = () => {
    const { t } = useTranslation();
    const { selectedMailbox, threads } = useMailboxContext();
    const canImportMessages = useAbility(Abilities.CAN_IMPORT_MESSAGES, selectedMailbox);
    const { selectedThreadIds } = useThreadSelection();
    const searchParams = useSearchParams();
    const { isMobile } = useResponsive();
    const showThreadView = !isMobile;
    const emptyMailbox = (selectedMailbox?.count_threads || 0) === 0
        && (threads?.results.length ?? 0) === 0;
    const { defaultLayout, onLayoutChange } = useDefaultLayout({
        groupId: showThreadView ? "threads" : "threads-single",
        storage: localStorage,
    });

    const showImportButton = useMemo(() => {
        // Only show import button if there are no threads in inbox or all messages folders and user has ability to import messages
        if (!canImportMessages || !emptyMailbox) return false;
        if (ViewHelper.isInboxView() || ViewHelper.isAllMessagesView()) return true;
        return false;
    }, [canImportMessages, searchParams]);

    if (emptyMailbox) {
        return <ThreadViewEmpty label={t('No threads')} showImportButton={showImportButton} />
    }

    return (
        <Group defaultLayout={defaultLayout} onLayoutChange={onLayoutChange} orientation="horizontal" className="threads__container">
            <Panel id={showThreadView ? "panel-thread-list" : "panel-thread-list-single"} className="thread-list-panel" defaultSize="35%" minSize="20%" maxSize="50%">
                <ThreadPanel />
            </Panel>
            {showThreadView && (
                <>
                    <Separator className="panel__resize-handle" />
                    <Panel id="panel-thread-view" className="thread-view-panel">
                        {selectedThreadIds.size > 0 ? (
                            <ThreadSelectionPlaceholder />
                        ) : (
                            <ThreadViewEmpty />
                        )}
                    </Panel>
                </>
            )}
        </Group>
    );
};

Mailbox.getLayout = function getLayout(page: React.ReactElement) {
    return (
        <MainLayout>
            <ThreadSelectionProvider>
                {page}
            </ThreadSelectionProvider>
        </MainLayout>
    )
}

export default Mailbox;
