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
            thread: t('The thread has been archived.'),
            message: t('The message has been archived.'),
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
