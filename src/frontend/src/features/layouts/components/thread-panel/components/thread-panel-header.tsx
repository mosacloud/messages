import { useSearchParams } from "next/navigation";
import { MAILBOX_FOLDERS } from "../../mailbox-panel/components/mailbox-list";
import { useLabelsList } from "@/features/api/gen";
import { useMailboxContext } from "@/features/providers/mailbox";
import { useTranslation } from "react-i18next";
import { useMemo, useState } from "react";
import { Button, Tooltip, Checkbox } from "@gouvfr-lasuite/cunningham-react";
import useRead from "@/features/message/use-read";
import { DropdownMenu, Icon } from "@gouvfr-lasuite/ui-kit";

type ThreadPanelTitleProps = {
    selectedThreadIds: Set<string>;
    isAllSelected: boolean;
    isSomeSelected: boolean;
    isSelectionMode: boolean;
    onSelectAll: () => void;
    onClearSelection: () => void;
    onEnableSelectionMode: () => void;
    onDisableSelectionMode: () => void;
}

const ThreadPanelTitle = ({ selectedThreadIds, isAllSelected, isSomeSelected, isSelectionMode, onSelectAll, onClearSelection, onEnableSelectionMode, onDisableSelectionMode }: ThreadPanelTitleProps) => {
    const { t } = useTranslation();
    const { markAsRead, markAsUnread } = useRead();
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const searchParams = useSearchParams();
    const isSearch = searchParams.has('search');
    const { threads, selectedMailbox, unselectThread } = useMailboxContext();
    const labelsQuery = useLabelsList({ mailbox_id: selectedMailbox?.id }, { query: { enabled: !!selectedMailbox && !!searchParams.get('label_slug') } })

    const title = useMemo(() => {
        if (searchParams.has('search')) return t('folder.search', { defaultValue: 'Search' });
        if (searchParams.has('label_slug')) return (labelsQuery.data?.data || []).find((label) => label.slug === searchParams.get('label_slug'))?.name;
        return MAILBOX_FOLDERS().find((folder) => new URLSearchParams(folder.filter).toString() === searchParams.toString())?.name;
    }, [searchParams, labelsQuery.data?.data, selectedMailbox, t])

    const handleSelectAllToggle = () => {
        if (isAllSelected) {
            onClearSelection();
        } else {
            onSelectAll();
        }
    };

    const threadIdsToMark = useMemo(() => {
        if (selectedThreadIds.size > 0) {
            return Array.from(selectedThreadIds);
        }
        return threads?.results.map((thread) => thread.id) || [];
    }, [selectedThreadIds, threads?.results]);

    const markAllTooltip = selectedThreadIds.size > 0
        ? t('Mark {{count}} threads as read', { count: selectedThreadIds.size, defaultValue_one: 'Mark {{count}} thread as read' })
        : t('Mark all as read');

    const markAllUnreadLabel = selectedThreadIds.size > 0
        ? t('Mark {{count}} threads as unread', { count: selectedThreadIds.size, defaultValue_one: 'Mark {{count}} thread as unread' })
        : t('Mark all as unread');

    return (
        <header className="thread-panel__header">
            <h2 className="thread-panel__header--title">{title}</h2>
            <div className="thread-panel__header--details">
                {(isSelectionMode || isSomeSelected) && (
                    <Checkbox
                        checked={isAllSelected}
                        indeterminate={isSomeSelected && !isAllSelected}
                        onChange={handleSelectAllToggle}
                        aria-label={isAllSelected ? t('Deselect all threads') : t('Select all threads')}
                        className="thread-panel__header--checkbox"
                    />
                )}
                <p>
                    {isSearch
                        ? t('{{count}} results', { count: threads?.count, defaultValue_one: '{{count}} result' })
                        : t('{{count}} messages', { count: threads?.count, defaultValue_one: '{{count}} message' })
                    }
                </p>
                <div className="thread-panel__bar">
                    <Tooltip content={markAllTooltip}>
                        <Button
                            onClick={() => {
                                markAsRead({
                                    threadIds: threadIdsToMark,
                                    onSuccess: () => {
                                        unselectThread();
                                        onClearSelection();
                                    }
                                });
                            }}
                            icon={<span className="material-icons">mark_email_read</span>}
                            variant="tertiary"
                            size="nano"
                            aria-label={markAllTooltip}
                        />
                    </Tooltip>
                    <DropdownMenu
                        isOpen={isDropdownOpen}
                        onOpenChange={setIsDropdownOpen}
                        options={[
                            {
                                label: markAllUnreadLabel,
                                icon: <span className="material-icons">mark_email_unread</span>,
                                callback: () => {
                                    markAsUnread({
                                        threadIds: threadIdsToMark,
                                        onSuccess: () => {
                                            unselectThread();
                                            onClearSelection();
                                        }
                                    })
                                },
                            },
                            {
                                label: isSelectionMode ? t('Disable thread selection') : t('Select threads'),
                                icon: <Icon name="checklist" />,
                                callback: () => {
                                    if (isSelectionMode) {
                                        onDisableSelectionMode();
                                    } else {
                                        onEnableSelectionMode();
                                    }
                                },
                                showSeparator: true,
                            },
                        ]}
                    >
                        <Tooltip content={t('More options')}>
                            <Button
                                onClick={() => setIsDropdownOpen(true)}
                                icon={<span className="material-icons">more_vert</span>}
                                variant="tertiary"
                                aria-label={t('More options')}
                                size="nano"
                            />
                        </Tooltip>
                    </DropdownMenu>
                </div>
            </div>
        </header>
    )
}

export default ThreadPanelTitle;
