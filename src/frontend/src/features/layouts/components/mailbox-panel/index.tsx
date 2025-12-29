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
import { useTranslation } from "react-i18next";

export const MailboxPanel = () => {
    const { t } = useTranslation();
    const router = useRouter();
    const searchParams = useSearchParams();
    const { selectedMailbox, mailboxes, queryStates, isUnifiedView } = useMailboxContext();
    const { closeLeftPanel } = useLayoutContext();
    const [isOpen, setIsOpen] = useState(false);

    const getMailboxOptions = () => {
        const options = [
            {
                label: t('All mailboxes'),
                value: 'unified',
            },
        ];
        if (mailboxes) {
            options.push(...mailboxes.map((mailbox) => ({
                label: mailbox.email,
                value: mailbox.id,
            })));
        }
        return options;
    }

    const getCurrentLabel = () => {
        if (isUnifiedView) return t('All mailboxes');
        return selectedMailbox?.email || t('Select mailbox');
    }

    return (
        <div className="mailbox-panel">
            <div className="mailbox-panel__header">
                <MailboxPanelActions />
                <HorizontalSeparator withPadding={false} />
                {/* Mailbox dropdown */}
                <div className="mailbox-panel__mailbox-title">
                    <DropdownMenu
                        options={getMailboxOptions()}
                        isOpen={isOpen}
                        onOpenChange={setIsOpen}
                        selectedValues={isUnifiedView ? ['unified'] : (selectedMailbox ? [selectedMailbox.id] : [])}
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
                            <Icon name={isUnifiedView ? "all_inbox" : "mail"} />
                            <span className="button__label">
                                {getCurrentLabel()}
                            </span>
                        </Button>
                    </DropdownMenu>
                </div>
            </div>
            {queryStates.mailboxes.isLoading ? <Spinner /> :
                (
                    <>
                        <MailboxList />
                        {selectedMailbox && <MailboxLabels mailbox={selectedMailbox} />}
                    </>
                )}
        </div>
    )
}
