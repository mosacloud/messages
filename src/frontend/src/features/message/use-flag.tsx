import { useFlagCreate } from "@/features/api/gen"
import { Thread, Message, FlagEnum, ChangeFlagRequestRequest } from "@/features/api/gen/models"
import { addToast, ToasterItem } from "../ui/components/toaster";
import { toast } from "react-toastify";
import { useTranslation } from "react-i18next";

type MarkAsOptions = {
    threadIds?: Thread["id"][],
    messageIds?: Message['id'][],
    onSuccess?: (data: ChangeFlagRequestRequest) => void,
}

type FlagOptions = {
    toastMessages?: FlagToastMessages;
    onSuccess?: (data: ChangeFlagRequestRequest) => void;
    showToast?: boolean;
}

type FlagToastMessages = {
    thread: (count: number) => string;
    message: (count: number) => string;
}

/**
 * Generic hook to update thread/message flags
 * !!! Do not use this hook directly, use the specialized hooks instead !!!
 */
const useFlag = (flag: FlagEnum, options?: FlagOptions) => {
    const toastId = `${flag.toLowerCase()}_TOAST_ID`;

    const { mutate, status } = useFlagCreate({
        mutation: {
            onSuccess: (_, { data }) => {
                options?.onSuccess?.(data);
                if (options?.showToast !== false && data.value === true) {
                    addToast(<FlagUpdateSuccessToast
                        flag={flag}
                        threadIds={data.thread_ids}
                        messageIds={data.message_ids}
                        toastId={toastId}
                        messages={options?.toastMessages}
                        onUndo={options?.onSuccess}
                    />, { toastId })
                }
            },
        }
    });

    const markAs =
        (status: boolean) =>
        ({ threadIds = [], messageIds = [], onSuccess }: MarkAsOptions) =>
            mutate({
                data: {
                    flag,
                    value: status,
                    thread_ids: threadIds,
                    message_ids: messageIds,
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
    toastId: string;
    messages?: FlagToastMessages;
    onUndo?: (data: ChangeFlagRequestRequest) => void;
}
const FlagUpdateSuccessToast = ({ flag, threadIds = [], messageIds = [], toastId, messages, onUndo }: FlagUpdateSuccessToastProps) => {
    const { t } = useTranslation();
    const { unmark } = useFlag(flag, { showToast: false });

    const undo = () => {
        unmark({
            threadIds: threadIds,
            messageIds: messageIds,
            onSuccess: (data) => {
                toast.dismiss(toastId);
                onUndo?.(data);
            }
        });
    }
    return (
        <ToasterItem
            type="info"
            actions={[{ label: t('Undo'), onClick: undo }]}
        >
            <span>{
                threadIds.length > 0 ?
                (messages?.thread?.(threadIds.length) ?? t('{{count}} threads have been updated.', { count: threadIds.length, defaultValue_one: 'The thread has been updated.' })) :
                (messages?.message?.(messageIds.length) ?? t('{{count}} messages have been updated.', { count: messageIds.length, defaultValue_one: 'The message has been updated.' }))
                }
            </span>
        </ToasterItem>
    )
};

export default useFlag;
