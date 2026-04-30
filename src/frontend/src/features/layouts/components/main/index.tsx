import { AppLayout } from "./layout";
import { PropsWithChildren } from "react";
import AuthenticatedView from "./authenticated-view";
import { MailboxProvider, useMailboxContext } from "@/features/providers/mailbox";
import { NoMailbox } from "./no-mailbox";
import { SentBoxProvider } from "@/features/providers/sent-box";
import { LeftPanel } from "./left-panel";
import { ModalStoreProvider } from "@/features/providers/modal-store";
import { ScrollRestoreProvider } from "@/features/providers/scroll-restore";
import { useTheme } from "@/features/providers/theme";
import { LayoutProvider, useLayoutDragContext } from "@/features/layouts/components/layout-context";
import Link from "next/link";

export const MainLayout = ({ children }: PropsWithChildren) => {
    return (
        <AuthenticatedView>
            <ScrollRestoreProvider>
                <MailboxProvider>
                    <SentBoxProvider>
                        <ModalStoreProvider>
                            <LayoutProvider draggable>
                                <MainLayoutContent>{children}</MainLayoutContent>
                            </LayoutProvider>
                        </ModalStoreProvider>
                    </SentBoxProvider>
                </MailboxProvider>
            </ScrollRestoreProvider>
        </AuthenticatedView>
    )
}

const MainLayoutContent = ({ children }: PropsWithChildren<{ simple?: boolean }>) => {
    const { mailboxes, queryStates } = useMailboxContext();
    const hasNoMailbox = queryStates.mailboxes.status === 'success' && mailboxes!.length === 0;
    const { theme, variant } = useTheme();
    const { isLeftPanelOpen, setIsLeftPanelOpen, isDragging } = useLayoutDragContext();

    return (
        <AppLayout
            enableResize
            isLeftPanelOpen={isLeftPanelOpen}
            setIsLeftPanelOpen={setIsLeftPanelOpen}
            leftPanelContent={<LeftPanel hasNoMailbox={hasNoMailbox} />}
            icon={<Link href="/"><img src={`/images/${theme}/app-logo-${variant}.svg`} alt="logo" height={40} /></Link>}
            hideLeftPanelOnDesktop={hasNoMailbox}
            isDragging={isDragging}
        >
            {hasNoMailbox ? (
                <NoMailbox />
            ) : (
                children
            )}
        </AppLayout>
    )
}
