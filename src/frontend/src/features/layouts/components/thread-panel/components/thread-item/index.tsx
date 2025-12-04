import { useTranslation } from "react-i18next"
import Link from "next/link"
import { useParams, useSearchParams } from "next/navigation"
import { useRef, useState } from "react"
import { createPortal } from "react-dom"
import clsx from "clsx"
import { DateHelper } from "@/features/utils/date-helper"
import { Thread } from "@/features/api/gen/models"
import { ThreadItemSenders } from "./thread-item-senders"
import { Badge } from "@/features/ui/components/badge"
import { ThreadDragPreview } from "./thread-drag-preview"
import { PORTALS } from "@/features/config/constants"
import { Tooltip } from "@gouvfr-lasuite/cunningham-react"
import { Icon, IconSize, IconType } from "@gouvfr-lasuite/ui-kit"
import { LabelBadge } from "@/features/ui/components/label-badge"

type ThreadItemProps = {
    thread: Thread
}

export const ThreadItem = ({ thread }: ThreadItemProps) => {
    const { t, i18n } = useTranslation();
    const params = useParams<{ mailboxId: string, threadId: string }>()
    const searchParams = useSearchParams()
    const [isDragging, setIsDragging] = useState(false)
    const dragPreviewContainer = useRef(document.getElementById(PORTALS.DRAG_PREVIEW));

    const handleDragStart = (e: React.DragEvent<HTMLAnchorElement>) => {
        setIsDragging(true)
        e.dataTransfer.setData('application/json', JSON.stringify({
            type: 'thread',
            threadId: thread.id,
            labels: thread.labels.map((label) => label.id),
        }))
        e.dataTransfer.effectAllowed = 'link'
        // Set the drag image
        if (dragPreviewContainer.current) {
            e.dataTransfer.setDragImage(dragPreviewContainer.current, 40, 40)
        }
    }
    const handleDragEnd = () => setIsDragging(false);

    return (
        <>
            <Link
                href={`/mailbox/${params?.mailboxId}/thread/${thread.id}?${searchParams}`}
                className={clsx(
                    'thread-item',
                    {
                        'thread-item--active': thread.id === params?.threadId,
                        'thread-item--dragging': isDragging,
                    },
                )}
                data-unread={thread.has_unread}
                draggable
                onDragStart={handleDragStart}
                onDragEnd={handleDragEnd}
            >
                <div>
                    <div className="thread-item__read-indicator" />
                </div>
                <div>
                    <div className="thread-item__row">
                        <div className="thread-item__column">
                            {thread.sender_names && thread.sender_names.length > 0 && (
                                <ThreadItemSenders senders={thread.sender_names} />
                            )}
                        </div>
                        <div className="thread-item__column thread-item__column--metadata">
                            {/* <Tooltip content={thread.labels.map((label) => label.display_name).join(', ')}>
                                <div className="thread-item__label-bullets">
                                    {thread.labels.slice(0, 4).map((label) => (
                                        <div key={`label-bullet-${label.id}`} className="thread-item__label-bullet" style={{ backgroundColor: label.color }} />
                                    ))}
                                    {thread.labels.length > 4 && (
                                        <div className="thread-item__label-bullet">
                                            +{thread.labels.length - 4}
                                        </div>
                                    )}
                                </div>
                            </Tooltip> */}

                            {thread.messaged_at && (
                                <span className="thread-item__date">
                                    {DateHelper.formatDate(thread.messaged_at, i18n.resolvedLanguage)}
                                </span>
                            )}
                        </div>
                    </div>
                    <div className="thread-item__row thread-item__row--subject">
                        <div className="thread-item__column">
                            <p className="thread-item__subject">{thread.subject || thread.snippet || t('No subject')}</p>
                        </div>
                        <div className="thread-item__column thread-item__column--badges">
                            {thread.has_attachments ? (
                                <Tooltip placement="bottom" content={t('This thread has an attachment')}>
                                    <Badge aria-label={t('Draft')} title={t('Draft')} color="neutral" variant="tertiary">
                                        <Icon name="attachment" size={IconSize.SMALL} />
                                    </Badge>
                                </Tooltip>
                            ) : null}
                            {thread.has_draft && (
                                <Tooltip placement="bottom" content={t('This thread has a draft')}>
                                    <Badge aria-label={t('Draft')} title={t('Draft')} color="brand" variant="secondary">
                                        <Icon type={IconType.FILLED} name="mode_edit" size={IconSize.SMALL} />
                                    </Badge>
                                </Tooltip>
                            )}
                            {/* <div className="thread-item__actions">
                        <Tooltip placement="bottom" content={t('Mark as important')}>
                            <Button color="tertiary-text" className="thread-item__action">
                                <span className="material-icons">
                                    flag
                                </span>
                            </Button>
                        </Tooltip>
                    </div> */}
                        </div>
                    </div>
                    <div className="thread-item__row">
                     {thread.labels.length > 0 && (
                         <div className="thread-item__labels">
                             {thread.labels.map((label) => (
                                 <LabelBadge key={label.id} label={label} compact />
                             ))}
                         </div>
                     )}
                 </div>
                </div>
            </Link>
            {isDragging && dragPreviewContainer.current && createPortal(
                <ThreadDragPreview count={1} />,
                dragPreviewContainer.current
            )}
        </>
    )
}
