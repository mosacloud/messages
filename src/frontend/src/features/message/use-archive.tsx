import { useMailboxContext } from "../providers/mailbox";
import { useTranslation } from "react-i18next";
import useFlag from "./use-flag";

/**
 * Hook to mark messages or threads as archived
 */
const useArchive = () => {
    const { t } = useTranslation();
    const { invalidateThreadMessages, invalidateThreadsStats } = useMailboxContext();

    const { mark, unmark, status } = useFlag('archived', {
        toastMessages: {
            thread: (count: number) => t('{{count}} threads have been archived.', { count: count, defaultValue_one: 'The thread has been archived.' }),
            message: (count: number) => t('{{count}} messages have been archived.', { count: count, defaultValue_one: 'The message has been archived.' }),
        },
        onSuccess: () => {
            invalidateThreadMessages();
            invalidateThreadsStats();
        }
    });

    return {
        markAsArchived: mark,
        markAsUnarchived: unmark,
        status
    }
};

export default useArchive;
