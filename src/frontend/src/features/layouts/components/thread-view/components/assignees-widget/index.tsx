import { UserAvatar } from "@gouvfr-lasuite/ui-kit";
import { Tooltip } from "@gouvfr-lasuite/cunningham-react";
import { useTranslation } from "react-i18next";
import { useAssignedUsers } from "@/features/message/use-assigned-users";
import { useIsSharedContext } from "@/hooks/use-is-shared-context";

const MAX_VISIBLE_AVATARS = 3;

type AssigneesWidgetProps = {
    onClick: () => void;
};

/**
 * Compact avatars group that surfaces the current assignees on the thread.
 * Rendered only when at least one user is assigned AND the thread is in a
 * shared context (shared mailbox or multiple mailbox accesses on the
 * thread). Clicking it opens the share/assign modal owned by
 * ThreadAccessesWidget.
 */
export const AssigneesWidget = ({ onClick }: AssigneesWidgetProps) => {
    const { t } = useTranslation();
    const isSharedContext = useIsSharedContext();
    const assignedUsers = useAssignedUsers();

    if (!isSharedContext) return null;
    if (assignedUsers.length === 0) return null;

    const visible = assignedUsers.slice(0, MAX_VISIBLE_AVATARS);
    const overflow = assignedUsers.length - visible.length;
    const tooltipContent = t('Assigned to {{names}}', {
        names: assignedUsers.map((u) => u.name).join(', '),
    });

    return (
        <Tooltip content={tooltipContent}>
            <button
                type="button"
                className="assignees-widget"
                onClick={onClick}
                aria-label={tooltipContent}
            >
                <span className="assignees-widget__avatars">
                    {visible.map((user) => (
                        <UserAvatar key={user.id} fullName={user.name} size="xsmall" />
                    ))}
                    {overflow > 0 && (
                        <span className="assignees-widget__overflow">+{overflow}</span>
                    )}
                </span>
            </button>
        </Tooltip>
    );
};
