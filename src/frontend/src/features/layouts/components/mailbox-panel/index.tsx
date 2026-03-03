import { DropdownMenu, HorizontalSeparator, Icon, Spinner } from "@gouvfr-lasuite/ui-kit"
import { MailboxPanelActions } from "./components/mailbox-actions"
import { MailboxList } from "./components/mailbox-list"
import { useMailboxContext } from "@/features/providers/mailbox";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useRouter } from "next/router";
import { useSearchParams } from "next/navigation";
import { useLayoutContext } from "../main";
import { MailboxLabels } from "./components/mailbox-labels";
import { useState } from "react";

export const MailboxPanel = () => {
    const router = useRouter();
    const searchParams = useSearchParams();
    const { selectedMailbox, mailboxes, queryStates } = useMailboxContext();
    const { closeLeftPanel } = useLayoutContext();
    const [isOpen, setIsOpen] = useState(false);

    const getMailboxOptions = () => {
        if (!mailboxes) return [];
        const sortedMailboxes = [...mailboxes].sort((a, b) => {
            const identityDiff = Number(b.is_identity) - Number(a.is_identity)
            if (identityDiff !== 0) return identityDiff;
            return a.email.localeCompare(b.email)
        })
        return sortedMailboxes.map((mailbox, index) => ({
            label: mailbox.email,
            value: mailbox.id,
            icon: mailbox.is_identity ? <Icon name="person" /> : <Icon name="group" />,
            showSeparator: mailbox.is_identity && (sortedMailboxes[index + 1] && !sortedMailboxes[index + 1].is_identity)
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
                                    router.push(`/mailbox/${value}?${searchParams.toString()}`);
                                }}
                            >
                                <Button
                                    className="mailbox-panel__mailbox-title__dropdown-button"
                                    color="neutral"
                                    variant="tertiary"
                                    icon={<Icon name={isOpen ? "arrow_drop_up" : "arrow_drop_down"} />}
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
                    <>

                        <MailboxList />
                        <MailboxLabels mailbox={selectedMailbox} />
                    </>
                )}
        </div>
    )
}
