import { UserAvatar } from "@gouvfr-lasuite/ui-kit";
import { useTranslation } from "react-i18next";

type AssignedUsersSectionProps = {
    assignedUsers: ReadonlyArray<{ id: string; name: string; email?: string }>;
    canUpdate: boolean;
    onUnassign: (userId: string) => void;
};

/**
 * Rendered through the ShareModal `children` slot, above the members list.
 * Title is dynamic ("Assigné à N personne") so the user instantly sees how
 * many people are in charge of this thread.
 */
export const AssignedUsersSection = ({ assignedUsers, canUpdate, onUnassign }: AssignedUsersSectionProps) => {
    const { t } = useTranslation();

    if (assignedUsers.length === 0) return null;

    return (
        <section className="share-modal-extensions__assigned">
            <h3 className="share-modal-extensions__assigned__title">
                {t('Assigned to {{count}} people', {
                    count: assignedUsers.length,
                    defaultValue_one: 'Assigned to {{count}} person',
                })}
            </h3>
            <ul className="share-modal-extensions__assigned__list">
                {assignedUsers.map((user) => (
                    <li key={user.id} className="share-modal-extensions__assigned__item">
                        <UserAvatar fullName={user.name} size="small" />
                        <div className="share-modal-extensions__assigned__identity">
                            <span className="share-modal-extensions__assigned__name">{user.name}</span>
                            {user.email && (
                                <span className="share-modal-extensions__assigned__email">{user.email}</span>
                            )}
                        </div>
                        {canUpdate && (
                            <button
                                type="button"
                                className="share-modal-extensions__assigned__remove"
                                onClick={() => onUnassign(user.id)}
                            >
                                {t('Remove')}
                            </button>
                        )}
                    </li>
                ))}
            </ul>
        </section>
    );
};
