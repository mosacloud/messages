import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { useTranslation } from "react-i18next";
import type { ThreadAccessDetail, UserWithoutAbilities } from "@/features/api/gen";

type UpgradeMailboxRoleModalProps = {
    isOpen: boolean;
    onClose: () => void;
    onConfirm: () => void;
    user: UserWithoutAbilities | null;
    access: ThreadAccessDetail | null;
    isPending?: boolean;
};

export const UpgradeMailboxRoleModal = ({
    isOpen,
    onClose,
    onConfirm,
    user,
    access,
    isPending,
}: UpgradeMailboxRoleModalProps) => {
    const { t } = useTranslation();
    const userLabel = user?.full_name || user?.email || "";
    const mailboxLabel = access?.mailbox.email || "";

    return (
        <Modal
            isOpen={isOpen}
            title={t('Grant editor access to the mailbox?')}
            size={ModalSize.MEDIUM}
            onClose={onClose}
        >
            <div className="upgrade-mailbox-role-modal">
                <p>
                    {t(
                        'The mailbox "{{mailbox}}" currently has read-only access on this thread. To assign {{user}}, the mailbox must be granted editor access on this thread.',
                        { mailbox: mailboxLabel, user: userLabel },
                    )}
                </p>
                <footer>
                    <Button variant="secondary" onClick={onClose} disabled={isPending}>
                        {t('Cancel')}
                    </Button>
                    <Button
                        onClick={onConfirm}
                        disabled={isPending}
                        icon={isPending && <Spinner />}
                    >
                        {t('Grant access and assign')}
                    </Button>
                </footer>
            </div>
        </Modal>
    );
};
