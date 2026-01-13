import { useState, useCallback, forwardRef, useEffect, useRef, useMemo } from "react";
import clsx from "clsx";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { useMailboxContext } from "@/features/providers/mailbox";
import { MessageFormMode } from "@/features/forms/components/message-form";
import MailHelper from "@/features/utils/mail-helper";
import useAbility, { Abilities } from "@/hooks/use-ability";
import { useThreadViewContext } from "../../provider";
import usePrevious from "@/hooks/use-previous";
import ThreadMessageBody from "./thread-message-body";
import MessageReplyForm from "../message-reply-form";
import ThreadMessageHeader from "./thread-message-header";
import ThreadMessageFooter from "./thread-message-footer";
import { ThreadMessageProps } from "./types";
import { BodyPart } from "./renderers";
import { DriveFile } from "@/features/forms/components/message-form/drive-attachment-picker";

export const ThreadMessage = forwardRef<HTMLSpanElement, ThreadMessageProps>(
    ({ message, isLatest, draftMessage, ...props }, ref) => {
        const replyFormRef = useRef<HTMLDivElement>(null);
        const threadViewContext = useThreadViewContext();
        const { selectedMailbox, queryStates } = useMailboxContext();
        const canSendMessages = useAbility(Abilities.CAN_SEND_MESSAGES, selectedMailbox);

        // Derived state
        const isMessageReady = threadViewContext.isMessageReady(message.id);
        const hasSeveralRecipients = useMemo(() => {
            return message.to.length + message.cc.length > 1;
        }, [message.to.length, message.cc.length]);

        // Extract drive attachments from HTML body parts
        const [processedHtmlBody, driveAttachments] = useMemo((): [BodyPart[], DriveFile[]] => {
            if (message.htmlBody.length === 0) {
                return [[], []] as const;
            }
            // Process each HTML body part for drive attachments
            const allDriveAttachments: ReturnType<typeof MailHelper.extractDriveAttachmentsFromHtmlBody>[1] = [];
            const processedParts = message.htmlBody.map(part => {
                const partContent = part?.content || "";
                const partType = part?.type || "text/html";
                const partId = part?.partId || "";
                const [content, attachments] = MailHelper.extractDriveAttachmentsFromHtmlBody(partContent);
                allDriveAttachments.push(...attachments);
                return { partId, type: partType, content };
            });
            return [processedParts, allDriveAttachments] as const;
        }, [message.htmlBody]);

        // Process text body parts
        const processedTextBody = useMemo(() => {
            if (message.textBody.length === 0) {
                return [];
            }
            return message.textBody.map(part => {
                const partContent = part?.content || "";
                const partType = part?.type || "text/plain";
                const partId = part?.partId || "";
                // Extract and process drive attachment URLs from text content
                const [content] = MailHelper.extractDriveAttachmentsFromTextBody(partContent);
                return { partId, type: partType, content };
            });
        }, [message.textBody]);

        // Determine which body parts to render (prefer HTML if available)
        const bodyPartsToRender = processedHtmlBody.length > 0 ? processedHtmlBody : processedTextBody;

        // Component state
        const [isThreadMessageBodyLoaded, setIsThreadMessageBodyLoaded] = useState(isMessageReady);
        const [isFolded, setIsFolded] = useState(!isLatest && !message.is_unread && !draftMessage?.is_draft);
        const [replyFormMode, setReplyFormMode] = useState<MessageFormMode | null>(() => {
            if (draftMessage?.is_draft) return 'reply';
            if (!message.is_draft || message.is_trashed) return null;
            return 'new';
        });
        const previousReplyFormMode = usePrevious<MessageFormMode | null>(replyFormMode);

        // Computed flags
        const showReplyForm = replyFormMode !== null;
        const showReplyButton = canSendMessages && isLatest && !showReplyForm && !message.is_draft && !message.is_trashed && !draftMessage;

        // Handlers
        const toggleFold = useCallback(() => {
            setIsFolded(prev => !prev);
        }, []);

        const handleCloseReplyForm = useCallback(() => {
            setReplyFormMode(null);
        }, []);

        // Effects
        useEffect(() => {
            const getReplyFormMode = (): MessageFormMode | null => {
                if (draftMessage?.is_draft) return 'reply';
                if (!message.is_draft || message.is_trashed) return null;
                return 'new';
            };
            setReplyFormMode(getReplyFormMode());
        }, [message, draftMessage]);

        // Smooth scroll to the reply form when it is opened by the user
        useEffect(() => {
            if (!threadViewContext.isReady) return;
            if (previousReplyFormMode === null && showReplyForm !== null) {
                if (replyFormRef.current) {
                    const container = document.querySelector<HTMLElement>('.thread-view')!;
                    container.scrollTo({ behavior: 'smooth', top: replyFormRef.current.offsetTop - 225 });
                }
            }
        }, [showReplyForm, threadViewContext.isReady, previousReplyFormMode]);

        useEffect(() => {
            if (isThreadMessageBodyLoaded && !queryStates.messages.isFetching) {
                threadViewContext.setMessageReadiness(message.id, true);
            }
        }, [isThreadMessageBodyLoaded, queryStates.messages.isFetching, message.id]);

        return (
            <section
                id={`thread-message-${message.id}`}
                className={clsx("thread-message", {
                    "thread-message--folded": isFolded || !isMessageReady,
                    "thread-message--sender": message.is_sender,
                })}
                data-unread={message.is_unread}
                data-trashed={message.is_trashed}
                {...props}
            >
                <ThreadMessageHeader
                    message={message}
                    draftMessage={draftMessage}
                    isLatest={isLatest}
                    isFolded={isFolded}
                    canSendMessages={canSendMessages}
                    hasSeveralRecipients={hasSeveralRecipients}
                    onToggleFold={toggleFold}
                    onSetReplyFormMode={setReplyFormMode}
                />

                <ThreadMessageBody
                    bodyParts={bodyPartsToRender}
                    attachments={message.attachments}
                    messageId={message.id}
                    isHidden={isFolded || !isMessageReady}
                    onLoad={() => setIsThreadMessageBodyLoaded(true)}
                />

                <ThreadMessageFooter
                    message={message}
                    driveAttachments={driveAttachments}
                    showReplyButton={showReplyButton}
                    hasSeveralRecipients={hasSeveralRecipients}
                    onSetReplyFormMode={setReplyFormMode}
                    intersectionRef={ref}
                />

                {isMessageReady && showReplyForm && (
                    <section className="thread-message__reply-form" ref={replyFormRef}>
                        <MessageReplyForm
                            mode={replyFormMode}
                            handleClose={handleCloseReplyForm}
                            message={draftMessage || message}
                        />
                    </section>
                )}

                {!isFolded && !isMessageReady && (
                    <div className="thread-message__loading">
                        <Spinner />
                    </div>
                )}
            </section>
        );
    }
);

ThreadMessage.displayName = "ThreadMessage";
