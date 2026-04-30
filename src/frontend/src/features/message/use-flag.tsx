import { useFlagCreate } from "@/features/api/gen"
import { Thread, Message, FlagEnum, ChangeFlagRequestRequest, Mailbox } from "@/features/api/gen/models"
import { addToast, ToasterItem } from "../ui/components/toaster";
import { toast, ToastContentProps } from "react-toastify";
import { useTranslation } from "react-i18next";

type MarkAsOptions = {
    threadIds?: Thread["id"][],
    messageIds?: Message['id'][],
    mailboxId?: string,
    readAt?: string | null,
    starredAt?: string | null,
    onSuccess?: (data: ChangeFlagRequestRequest) => void,
}

type FlagOptions = {
    toastMessages?: FlagToastMessages;
    onSuccess?: (data: ChangeFlagRequestRequest) => void;
    showToast?: boolean;
}

type FlagToastMessages = {
    thread: (updatedCount: number, submittedCount: number) => string;
    message: (updatedCount: number, submittedCount: number) => string;
}

/**
 * Generic hook to update thread/message flags
 * !!! Do not use this hook directly, use the specialized hooks instead !!!
 */
const useFlag = (flag: FlagEnum, options?: FlagOptions) => {
    const toastIdSuffix = `${flag.toLowerCase()}_TOAST_ID`;

    const { mutate, status } = useFlagCreate({
        mutation: {
            onSuccess: (response, { data }) => {
                options?.onSuccess?.(data);
                if (options?.showToast !== false && data.value === true) {
                    const responseData = response.data as Record<string, unknown>;
                    const updatedCount = typeof responseData.updated_threads === 'number'
                        ? responseData.updated_threads
                        : undefined;
                    const threadIds = data.thread_ids ?? [];
                    const type = updatedCount === undefined ? 'success'
                        : updatedCount === 0 ? 'error'
                        : (threadIds.length > 0 && updatedCount < threadIds.length) ? 'warning'
                        : 'success';
                    const toastId = `${toastIdSuffix}--${type}`;
                    addToast(<FlagUpdateSuccessToast
                        flag={flag}
                        threadIds={data.thread_ids}
                        messageIds={data.message_ids}
                        mailboxId={data.mailbox_id}
                        toastId={toastId}
                        messages={options?.toastMessages}
                        onUndo={options?.onSuccess}
                        updatedCount={updatedCount}
                    />, { toastId })
                }
            },
        }
    });

    const markAs =
        (status: boolean) =>
        ({ threadIds = [], messageIds = [], mailboxId, readAt, starredAt, onSuccess }: MarkAsOptions) =>
            mutate({
                data: {
                    flag,
                    value: status,
                    thread_ids: threadIds,
                    message_ids: messageIds,
                    mailbox_id: mailboxId,
                    ...(readAt !== undefined && { read_at: readAt }),
                    ...(starredAt !== undefined && { starred_at: starredAt }),
                },
            }, {
                onSuccess: (_, { data }) => onSuccess?.(data)
            });

    return {
        mark: markAs(true),
        unmark: markAs(false),
        status
    };
};

type FlagUpdateSuccessToastProps = {
    flag: FlagEnum;
    threadIds?: Thread['id'][];
    messageIds?: Message['id'][];
    mailboxId?: Mailbox['id'];
    toastId: string;
    messages?: FlagToastMessages;
    onUndo?: (data: ChangeFlagRequestRequest) => void;
    updatedCount?: number;
}
const FlagUpdateSuccessToast = ({ flag, threadIds = [], messageIds = [], mailboxId, toastId, messages, onUndo, updatedCount, closeToast }: FlagUpdateSuccessToastProps & Partial<ToastContentProps>) => {
    const { t } = useTranslation();
    const { unmark } = useFlag(flag, { showToast: false });

    const isThreadScope = threadIds.length > 0;
    const submittedCount = isThreadScope ? threadIds.length : messageIds.length;
    const isPartial = isThreadScope && updatedCount !== undefined && updatedCount > 0 && updatedCount < threadIds.length;
    const isNone = updatedCount !== undefined && updatedCount === 0 && submittedCount > 0;
    const displayCount = isNone ? 0 : isPartial ? updatedCount! : submittedCount;

    const undo = () => {
        unmark({
            threadIds: threadIds,
            messageIds: messageIds,
            mailboxId,
            onSuccess: (data) => {
                toast.dismiss(toastId);
                onUndo?.(data);
            }
        });
    }

    const toastType = isNone ? 'error' : isPartial ? 'warning' : 'info';
    const mainMessage = threadIds.length > 0
        ? (messages?.thread?.(displayCount, submittedCount) ?? t('{{count}} threads have been updated.', { count: displayCount, defaultValue_one: 'The thread has been updated.' }))
        : (messages?.message?.(displayCount, submittedCount) ?? t('{{count}} messages have been updated.', { count: displayCount, defaultValue_one: 'The message has been updated.' }));

    return (
        <ToasterItem
            type={toastType}
            actions={isNone ? [] : [{ label: t('Undo'), onClick: undo }]}
            closeToast={closeToast}
        >
            <div>
                <p>{mainMessage}</p>
                {(isPartial || isNone) && (
                    <p>{t('You may not have sufficient permissions for all selected threads.')}</p>
                )}
            </div>
        </ToasterItem>
    )
};

export default useFlag;
