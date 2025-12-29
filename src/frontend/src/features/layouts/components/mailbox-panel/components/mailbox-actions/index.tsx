import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useMailboxContext } from "@/features/providers/mailbox";
import { useLayoutContext } from "../../../main";
import useAbility, { Abilities } from "@/hooks/use-ability";
import { Icon, IconType } from "@gouvfr-lasuite/ui-kit";

export const MailboxPanelActions = () => {
    const { t } = useTranslation();
    const router = useRouter();
    const { selectedMailbox, mailboxes, isUnifiedView, refetchMailboxes } = useMailboxContext();
    const { closeLeftPanel } = useLayoutContext();
    const canWriteMessages = useAbility(Abilities.CAN_WRITE_MESSAGES, selectedMailbox);

    // In unified view, use the first mailbox (user can change 'from' in composer)
    const defaultMailbox = isUnifiedView ? mailboxes?.[0] : selectedMailbox;
    const canWrite = isUnifiedView ? !!defaultMailbox : canWriteMessages;

    const goToNewMessageForm = (event: React.MouseEvent<HTMLButtonElement | HTMLAnchorElement>) => {
        event.preventDefault();
        if (!canWrite || !defaultMailbox) return;
        closeLeftPanel();
        router.push(`/mailbox/${defaultMailbox.id}/new`);
    }

    if (!defaultMailbox) return null;

    return (
        <div className="mailbox-panel-actions">
            <div>
            {
                <Button
                    onClick={goToNewMessageForm}
                    href={`/mailbox/${defaultMailbox.id}/new`}
                    icon={<Icon name="edit_note" type={IconType.OUTLINED} aria-hidden="true" />}
                    disabled={!canWrite}
                >
                    {t("New message")}
                </Button>
            }
            </div>
            <div className="mailbox-panel-actions__extra">
                <Button
                    icon={<span className="material-icons">autorenew</span>}
                    variant="tertiary"
                    aria-label={t('Refresh')}
                    onClick={refetchMailboxes}
                />
            </div>
        </div>
    )
}

