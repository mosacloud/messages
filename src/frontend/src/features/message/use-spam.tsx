import { useTranslation } from "react-i18next";
import useFlag from "./use-flag";
import { useMailboxContext } from "../providers/mailbox";

/**
 * Hook to mark messages or threads as spam
 */
const useSpam = () => {
    const { t } = useTranslation();
    const { invalidateThreadMessages, invalidateThreadsStats } = useMailboxContext();
    const { mark, unmark, status } = useFlag('spam', {
        toastMessages: {
            thread: t('The thread has been marked as spam.'),
            message: t('The message has been marked as spam.'),
        },
        onSuccess: () => {
            invalidateThreadMessages();
            invalidateThreadsStats();
        },
    });

    return {
        markAsSpam: mark,
        markAsNotSpam: unmark,
        status
    };
};

export default useSpam;
