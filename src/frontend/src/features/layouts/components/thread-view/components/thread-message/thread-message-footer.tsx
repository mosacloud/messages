import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { AttachmentList } from "../thread-attachment-list";
import { ThreadMessageFooterProps } from "./types";

const ThreadMessageFooter = ({
    message,
    driveAttachments,
    showReplyButton,
    hasSeveralRecipients,
    onSetReplyFormMode,
    intersectionRef,
}: ThreadMessageFooterProps) => {
    const { t } = useTranslation();

    const hasAttachments = !message.is_draft && (message.attachments.length > 0 || driveAttachments.length > 0);

    return (
        <footer className="thread-message__footer">
            <span
                className="thread-message__intersection-trigger"
                ref={intersectionRef}
                data-message-id={message.id}
            />
            {hasAttachments && (
                <AttachmentList attachments={[...message.attachments, ...driveAttachments]} />
            )}
            {showReplyButton && (
                <div className="thread-message__footer-actions">
                    {hasSeveralRecipients && (
                        <Button
                            color="brand"
                            variant="primary"
                            size="small"
                            icon={<span className="material-icons">reply_all</span>}
                            aria-label={t('Reply all')}
                            onClick={() => onSetReplyFormMode('reply_all')}
                        >
                            {t('Reply all')}
                        </Button>
                    )}
                    <Button
                        variant={hasSeveralRecipients ? 'tertiary' : 'primary'}
                        icon={<span className="material-icons">reply</span>}
                        aria-label={t('Reply')}
                        size="small"
                        onClick={() => onSetReplyFormMode('reply')}
                    >
                        {t('Reply')}
                    </Button>
                    <Button
                        variant='tertiary'
                        size="small"
                        icon={<span className="material-icons">forward</span>}
                        onClick={() => onSetReplyFormMode('forward')}
                    >
                        {t('Forward')}
                    </Button>
                </div>
            )}
        </footer>
    );
};

export default ThreadMessageFooter;
