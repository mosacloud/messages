import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams, useParams } from "next/navigation";
import { useRouter } from "next/router";
import Link from "next/link";
import clsx from "clsx";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";
import { ThreadGroup as ThreadGroupType } from "../../hooks/use-linked-thread-groups";
import { ThreadItem } from "../thread-item";
import { DateHelper } from "@/features/utils/date-helper";
import { ThreadItemSenders } from "../thread-item/thread-item-senders";
import { Badge } from "@/features/ui/components/badge";

type ThreadGroupProps = {
    group: ThreadGroupType;
    onToggleSelection: (
        threadId: string,
        index: number,
        shiftKey: boolean,
        ctrlKey: boolean,
        arrowKey?: "up" | "down"
    ) => void;
    selectedThreadIds: Set<string>;
    isSelectionMode: boolean;
    baseIndex: number;
};

export const ThreadGroup = ({
    group,
    onToggleSelection,
    selectedThreadIds,
    isSelectionMode,
    baseIndex,
}: ThreadGroupProps) => {
    const { t, i18n } = useTranslation();
    const searchParams = useSearchParams();
    const params = useParams<{ mailboxId: string }>();
    const router = useRouter();
    const [isExpanded, setIsExpanded] = useState(false);

    const { primaryThread, threads, totalMessages, latestDate, mailboxes } = group;

    // Check if any thread in group is selected
    const hasSelectedThread = threads.some(t => selectedThreadIds.has(t.id));

    // Check if primary thread has unread
    const hasUnread = threads.some(t => t.has_unread);

    // Check if any thread has attachments
    const hasAttachments = threads.some(t => t.has_attachments);

    // Check if any thread has draft
    const hasDraft = threads.some(t => t.has_draft);

    const handleHeaderClick = (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsExpanded(!isExpanded);
        // Navigate to show the group overview (no context = shows overview)
        const newParams = new URLSearchParams(searchParams);
        newParams.delete('context');
        router.push(`/mailbox/${params?.mailboxId}/thread/${primaryThread.id}?${newParams}`, undefined, { shallow: false });
    };

    return (
        <div className={clsx("thread-group", {
            "thread-group--expanded": isExpanded,
            "thread-group--has-selected": hasSelectedThread,
        })}>
            {/* Group Header - styled like ThreadItem */}
            <button
                className={clsx("thread-item thread-group__header", {
                    "thread-item--selected": hasSelectedThread,
                })}
                onClick={handleHeaderClick}
                aria-expanded={isExpanded}
                data-unread={hasUnread}
            >
                <div>
                    <Icon
                        name={isExpanded ? "expand_more" : "chevron_right"}
                        size={IconSize.SMALL}
                        className="thread-group__chevron"
                    />
                    <div className="thread-item__read-indicator" />
                </div>
                <div>
                    <div className="thread-item__row">
                        <div className="thread-item__column">
                            {primaryThread.sender_names && primaryThread.sender_names.length > 0 && (
                                <ThreadItemSenders senders={primaryThread.sender_names} />
                            )}
                        </div>
                        <div className="thread-item__column thread-item__column--metadata">
                            {latestDate && (
                                <span className="thread-item__date">
                                    {DateHelper.formatDate(latestDate, i18n.resolvedLanguage)}
                                </span>
                            )}
                        </div>
                    </div>
                    <div className="thread-item__row thread-item__row--subject">
                        <div className="thread-item__column">
                            <p className="thread-item__subject">
                                {primaryThread.subject || primaryThread.snippet || t('No subject')}
                            </p>
                        </div>
                        <div className="thread-item__column thread-item__column--badges">
                            {hasDraft && (
                                <Badge aria-label={t('Draft')} title={t('Draft')} color="neutral" variant="tertiary" compact>
                                    <Icon name="mode_edit" className="icon--size-sm" />
                                </Badge>
                            )}
                            {hasAttachments && (
                                <Badge aria-label={t('Attachments')} title={t('Attachments')} color="neutral" variant="tertiary" compact>
                                    <Icon name="attachment" size={IconSize.SMALL} />
                                </Badge>
                            )}
                            {/* Message count badge */}
                            <Badge color="neutral" variant="tertiary" compact title={t('{{count}} messages', { count: totalMessages })}>
                                {totalMessages}
                            </Badge>
                        </div>
                    </div>
                    {/* Mailboxes in bottom row - only when collapsed */}
                    {!isExpanded && mailboxes.length > 0 && (
                        <div className="thread-item__row">
                            <div className="thread-item__mailboxes">
                                {mailboxes.map((mailbox) => (
                                    <Link
                                        key={mailbox.id}
                                        href={`/mailbox/${mailbox.id}/thread/${mailbox.threadId}?${searchParams}`}
                                        className="thread-item__mailbox"
                                        title={mailbox.email}
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        {mailbox.email}
                                    </Link>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </button>

            {/* Expanded Thread List */}
            {isExpanded && (
                <div className="thread-group__threads">
                    {threads.map((thread, index) => (
                        <ThreadItem
                            key={thread.id}
                            thread={thread}
                            index={baseIndex + index}
                            isSelected={selectedThreadIds.has(thread.id)}
                            onToggleSelection={onToggleSelection}
                            selectedThreadIds={selectedThreadIds}
                            isSelectionMode={isSelectionMode}
                        />
                    ))}
                </div>
            )}
        </div>
    );
};
