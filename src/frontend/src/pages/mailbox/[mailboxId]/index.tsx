import { MainLayout } from "@/features/layouts/components/main";
import { useResponsive } from "@/features/layouts/components/main/hooks/useResponsive";
import { ThreadPanel } from "@/features/layouts/components/thread-panel";
import { useMailboxContext } from "@/features/providers/mailbox";
import Image from "next/image";
import { useTranslation } from "react-i18next";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";

const Mailbox = () => {
    const { t } = useTranslation();
    const { threads } = useMailboxContext();
    const { isDesktop } = useResponsive();

    return (
        <PanelGroup autoSaveId="threads" direction="horizontal" className="threads__container">
            <Panel className="thread-list-panel" defaultSize={35} minSize={20}>
                <ThreadPanel />
            </Panel>
            {(isDesktop && (threads?.results?.length ?? 0) > 0) && (
                <>
                    <PanelResizeHandle className="panel__resize-handle" />
                    <Panel className="thread-view-panel" defaultSize={65} minSize={50}>
                        <div className="thread-view thread-view--empty">
                            <div>
                                <Image src="/images/svg/read-mail.svg" alt="" width={60} height={60} />
                                <p>{t('Select a thread')}</p>
                            </div>
                        </div>
                    </Panel>
                </>
            )}
        </PanelGroup>
    )
}

Mailbox.getLayout = function getLayout(page: React.ReactElement) {
    return (
        <MainLayout>
            {page}
        </MainLayout>
    )
}

export default Mailbox;
