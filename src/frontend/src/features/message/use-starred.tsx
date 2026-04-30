import { useMailboxContext } from "../providers/mailbox";
import { useTranslation } from "react-i18next";
import useFlag from "./use-flag";

type MarkAsStarredOptions = {
    threadIds: string[];
    starredAt?: string;
    onSuccess?: () => void;
}

/**
 * Hook to mark threads as starred.
 * Starred state is scoped per mailbox via ThreadAccess.starred_at.
 */
const useStarred = () => {
    const { t } = useTranslation();
    const { selectedMailbox, invalidateThreadMessages, invalidateThreadsStats } = useMailboxContext();
    const mailboxId = selectedMailbox?.id;

    const { mark, unmark, status } = useFlag('starred', {
        toastMessages: {
            thread: (updatedCount, submittedCount) => {
                if (updatedCount === 0) return t('No thread could be starred.');
                if (updatedCount < submittedCount) return t('{{count}} out of {{total}} threads are now starred.', { count: updatedCount, total: submittedCount, defaultValue_one: '{{count}} out of {{total}} thread is now starred.' });
                return t('{{count}} threads are now starred.', { count: updatedCount, defaultValue_one: 'The thread is now starred.' });
            },
            message: (updatedCount, submittedCount) => {
                if (updatedCount === 0) return t('No message could be starred.');
                if (updatedCount < submittedCount) return t('{{count}} out of {{total}} messages are now starred.', { count: updatedCount, total: submittedCount, defaultValue_one: '{{count}} out of {{total}} message is now starred.' });
                return t('{{count}} messages are now starred.', { count: updatedCount, defaultValue_one: 'The message is now starred.' });
            },
        },
        onSuccess: (data) => {
            const starredAt = data.value ? (data.starred_at ?? new Date().toISOString()) : null;
            invalidateThreadMessages({
                type: 'update',
                metadata: { ids: [], threadIds: data.thread_ids ?? [] },
                payload: {},
                threadAccessStarredAt: mailboxId
                    ? { mailboxId, starredAt }
                    : undefined,
                skipThreadsRefetch: true,
            });
            invalidateThreadsStats();
        },
    });

    const markAsStarred = ({ threadIds, starredAt, onSuccess }: MarkAsStarredOptions) => {
        mark({
            threadIds,
            mailboxId,
            starredAt,
            onSuccess: () => onSuccess?.(),
        });
    };

    const markAsUnstarred = ({ threadIds, onSuccess }: MarkAsStarredOptions) => {
        unmark({
            threadIds,
            mailboxId,
            onSuccess: () => onSuccess?.(),
        });
    };

    return {
        markAsStarred,
        markAsUnstarred,
        status,
    };
};

export default useStarred;
