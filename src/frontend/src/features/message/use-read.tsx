import { useMailboxContext } from "../providers/mailbox";
import useFlag from "./use-flag";

/**
 * Hook to mark messages or threads as read or unread
 */
const useRead = () => {
    const { invalidateThreadMessages, invalidateThreadsStats } = useMailboxContext();

    const { mark, unmark, status } = useFlag('unread', {
        showToast: false,
        onSuccess: (data) => {
            invalidateThreadMessages({
                type: 'update',
                metadata: { ids: data.message_ids ?? [], threadIds: data.thread_ids ?? [] },
                payload: { is_unread: data.value, read_at: data.value ? new Date().toISOString() : null }
            });
            invalidateThreadsStats();
        }
    });

    return {
        markAsRead: unmark,
        markAsUnread: mark,
        status
    };
}

export default useRead;
