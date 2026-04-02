import { useMailboxContext } from "../providers/mailbox";
import useFlag from "./use-flag";

type MarkAsReadAtOptions = {
    threadIds: string[];
    readAt: string | null;
    onSuccess?: () => void;
}

/**
 * Hook to mark threads as read up to a given timestamp.
 *
 * - readAt = ISO timestamp → messages created before that are read
 * - readAt = null → all messages are unread
 *
 * The flag API value is derived: readAt === null means unread (value=true).
 */
const useRead = () => {
    const { selectedMailbox, invalidateThreadMessages, invalidateThreadsStats } = useMailboxContext();

    const { mark, unmark, status } = useFlag('unread', {
        showToast: false,
    });

    const mailboxId = selectedMailbox?.id;

    const markAsReadAt = ({ threadIds, readAt, onSuccess }: MarkAsReadAtOptions) => {
        const isUnread = readAt === null;
        const flagFn = isUnread ? mark : unmark;

        flagFn({
            threadIds,
            mailboxId,
            readAt,
            onSuccess: (data) => {
                invalidateThreadMessages({
                    type: 'update',
                    metadata: { ids: [], threadIds: data.thread_ids ?? [] },
                    payload: { is_unread: isUnread },
                    threadAccessReadAt: mailboxId
                        ? { mailboxId, readAt: data.read_at ?? null }
                        : undefined,
                    readAt: data.read_at ?? null,
                    skipThreadsRefetch: true,
                });
                invalidateThreadsStats();
                onSuccess?.();
            },
        });
    };

    return {
        markAsReadAt,
        status,
    };
}

export default useRead;
