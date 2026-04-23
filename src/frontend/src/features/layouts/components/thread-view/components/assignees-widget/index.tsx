import { Button, Tooltip } from "@gouvfr-lasuite/cunningham-react";
import { useTranslation } from "react-i18next";
import { useAssignedUsers } from "@/features/message/use-assigned-users";
import { useIsSharedContext } from "@/hooks/use-is-shared-context";
import { AssigneesAvatarGroup } from "@/features/ui/components/assignees-avatar-group";



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

    const tooltipContent = t('Assigned to {{names}}', {
        names: assignedUsers.map((u) => u.name).join(', '),
    });

    return (
        <Tooltip content={tooltipContent}>
            <Button
          type="button"
          variant="tertiary"
                className="assignees-widget"
                onClick={onClick}
          aria-label={tooltipContent}
          size="nano"
            >
                <AssigneesAvatarGroup users={assignedUsers} maxAvatars={3} />
            </Button>
        </Tooltip>
    );
};
