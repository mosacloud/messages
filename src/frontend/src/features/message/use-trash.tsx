import { useMailboxContext } from "../providers/mailbox";
import { useTranslation } from "react-i18next";
import useFlag from "./use-flag";

/**
 * Hook to mark messages or threads as trashed
 */
const useTrash = () => {
    const { t } = useTranslation();
    const { invalidateThreadMessages, invalidateThreadsStats } = useMailboxContext();

    const { mark, unmark, status } = useFlag('trashed', {
        toastMessages: {
            thread: (count: number) => t('{{count}} threads have been deleted.', { count: count, defaultValue_one: 'The thread has been deleted.' }),
            message: (count: number) => t('{{count}} messages have been deleted.', { count: count, defaultValue_one: 'The message has been deleted.' }),
        },
        onSuccess: () => {
            invalidateThreadMessages();
            invalidateThreadsStats();
        }
    });

    return {
        markAsTrashed: mark,
        markAsUntrashed: unmark,
        status
    };
};

export default useTrash;
