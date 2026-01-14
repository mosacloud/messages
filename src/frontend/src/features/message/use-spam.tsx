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
            thread: (count: number) => t('{{count}} threads have been reported as spam.', { count: count, defaultValue_one: 'The thread has been reported as spam.' }),
            message: (count: number) => t('{{count}} messages have been reported as spam.', { count: count, defaultValue_one: 'The message has been reported as spam.' }),
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
