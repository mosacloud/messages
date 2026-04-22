import { UserAvatar } from "@gouvfr-lasuite/ui-kit";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useTranslation } from "react-i18next";
import type { ThreadAccessDetail, UserWithoutAbilities } from "@/features/api/gen";

type AccessUsersListProps = {
    access: ThreadAccessDetail;
    assignedUserIds: ReadonlySet<string>;
    canAssign: boolean;
    onAssign: (user: UserWithoutAbilities, access: ThreadAccessDetail) => void;
};

/**
 * Renders the list of assignable users of a shared mailbox directly below
 * the mailbox row (no accordion). A mailbox is considered "shared" when
 * it has more than one assignable user OR when its `is_identity` flag is
 * false (e.g. a team alias with only one member today but open to more).
 * Personal identity mailboxes with a single user fall through to an
 * inline "Assign" CTA on the row itself — handled in the parent widget.
 */
export const AccessUsersList = ({
    access,
    assignedUserIds,
    canAssign,
    onAssign,
}: AccessUsersListProps) => {
    const { t } = useTranslation();
    if (!access.users || access.users.length === 0) return null;
    const isShared = access.users.length > 1 || access.mailbox.is_identity === false;
    if (!isShared) return null;

    return (
        <ul className="share-modal-extensions__users">
            {access.users.map((user) => {
                const isAssigned = assignedUserIds.has(user.id);
                return (
                    <li key={user.id} className="share-modal-extensions__users__item">
                        <UserAvatar fullName={user.full_name || user.email || ""} size="small" />
                        <div className="share-modal-extensions__users__identity">
                            <span className="share-modal-extensions__users__name">
                                {user.full_name || user.email}
                            </span>
                            {user.full_name && user.email && (
                                <span className="share-modal-extensions__users__email">{user.email}</span>
                            )}
                        </div>
                        {!isAssigned && canAssign && (
                            <Button
                                onClick={() => onAssign(user, access)}
                                size="small"
                                variant="secondary"
                                className="share-modal-extensions__users__cta"
                            >
                                {t('Assign')}
                            </Button>
                        )}
                    </li>
                );
            })}
        </ul>
    );
};
