import { Message } from "@/features/api/gen";
import { MessageForm, MessageFormMode } from "@/features/forms/components/message-form";
import { useQueryClient } from "@tanstack/react-query";

type MessageReplyFormProps = {
    handleClose: () => void;
    mode?: MessageFormMode;
    message: Message;
};

const MessageReplyForm = ({ handleClose, message, mode }: MessageReplyFormProps) => {
    const queryClient = useQueryClient();

    return (
        <div className="message-reply-form-container">
            <MessageForm
                draftMessage={message.is_draft ? message : undefined}
                parentMessage={message.is_draft ? undefined : message}
                mode={mode}
                onSuccess={() => {
                    // Close right away: MessageForm has optimistically un-drafted
                    // the message, so the thread already shows it as sending.
                    handleClose();
                    // Reconcile with the server state (delivery status, etc.) in
                    // the background without blocking the form close.
                    void queryClient.refetchQueries({ queryKey: ["messages", message.thread_id] });
                }}
                onClose={handleClose}
            />
        </div>
    );
};

export default MessageReplyForm;
