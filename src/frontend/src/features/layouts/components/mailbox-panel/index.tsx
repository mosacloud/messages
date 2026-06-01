import { DropdownMenu, HorizontalSeparator, Icon, Spinner } from "@gouvfr-lasuite/ui-kit"
import { ChevronDown, ChevronUp } from "@gouvfr-lasuite/ui-kit/icons";
import { MailboxPanelActions } from "./components/mailbox-actions"
import { MailboxList } from "./components/mailbox-list"
import { useMailboxContext } from "@/features/providers/mailbox";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useNavigate } from "@tanstack/react-router";
import { useUrlSearchParams } from "@/hooks/use-url-search-params";
import { useLayoutContext } from "@/features/layouts/components/layout-context";
import { MailboxLabels } from "./components/mailbox-labels";
import { useState } from "react";
import { Group, Panel, Separator, useDefaultLayout } from "react-resizable-panels";
import MailboxHelper from "@/features/utils/mailbox-helper";

export const MailboxPanel = () => {
    const navigate = useNavigate();
    const searchParams = useUrlSearchParams();
    const { selectedMailbox, mailboxes, queryStates } = useMailboxContext();
    const { closeLeftPanel } = useLayoutContext();
    const [isOpen, setIsOpen] = useState(false);
    const { defaultLayout, onLayoutChange } = useDefaultLayout({
        groupId: "mailbox-panel-sections",
        storage: typeof window !== "undefined" ? localStorage : undefined,
    });

    const getMailboxOptions = () => {
        if (!mailboxes) return [];
        const sortedMailboxes = MailboxHelper.sortByKind(mailboxes);
        return sortedMailboxes.map((mailbox, index) => ({
            label: mailbox.email,
            value: mailbox.id,
            icon: mailbox.is_identity ? <Icon name="person" /> : <Icon name="group" />,
            showSeparator: MailboxHelper.showSeparatorAfter(sortedMailboxes, index)
        }));
    }

    return (
        <div className="mailbox-panel">
            <div className="mailbox-panel__header">
                <MailboxPanelActions />
                <HorizontalSeparator withPadding={false} />
                { selectedMailbox && (
                <div className="mailbox-panel__mailbox-title">
                            <DropdownMenu
                                options={getMailboxOptions()}
                                isOpen={isOpen}
                                onOpenChange={setIsOpen}
                                selectedValues={[selectedMailbox.id]}
                                onSelectValue={(value) => {
                                    closeLeftPanel();
                                    navigate({ to: '/mailbox/$mailboxId', params: { mailboxId: value }, search: Object.fromEntries(searchParams) });
                                }}
                            >
                                <Button
                                    className="mailbox-panel__mailbox-title__dropdown-button"
                                    color="neutral"
                                    variant="tertiary"
                                    icon={isOpen ? <ChevronUp size="small" /> : <ChevronDown size="small" />}
                                    iconPosition="right"
                                    onClick={() => setIsOpen(!isOpen)}
                                >
                                    <span className="button__label">{selectedMailbox.email}</span>
                                </Button>
                            </DropdownMenu>
                        </div>
                )}
            </div>
            {!selectedMailbox || queryStates.mailboxes.isLoading ? <Spinner /> :
                (
                    <Group
                        orientation="vertical"
                        className="mailbox-panel__body"
                        defaultLayout={defaultLayout}
                        onLayoutChange={onLayoutChange}
                    >
                        <Panel id="mailbox-panel-folders" defaultSize="40%" minSize="20%">
                            <MailboxList />
                        </Panel>
                        <Separator className="panel__resize-handle" />
                        <Panel id="mailbox-panel-labels" defaultSize="60%" minSize="20%">
                            <MailboxLabels mailbox={selectedMailbox} />
                        </Panel>
                    </Group>
                )}
        </div>
    )
}
