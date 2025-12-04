import { useSearchParams } from "next/navigation";
import { MAILBOX_FOLDERS } from "../../mailbox-panel/components/mailbox-list";
import { useLabelsList } from "@/features/api/gen";
import { useMailboxContext } from "@/features/providers/mailbox";
import { useTranslation } from "react-i18next";
import { useMemo, useState } from "react";
import { Button, Tooltip } from "@gouvfr-lasuite/cunningham-react";
import useRead from "@/features/message/use-read";
import { DropdownMenu } from "@gouvfr-lasuite/ui-kit";

const ThreadPanelTitle = () => {
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
    }, [searchParams, labelsQuery.data?.data, selectedMailbox])

    return (
        <header className="thread-panel__header">
            <h2 className="thread-panel__header--title">{title}</h2>
            <div className="thread-panel__header--details">
                <p>
                    {isSearch
                        ? t('{{count}} results', { count: threads?.count, defaultValue_one: '{{count}} result' })
                        : t('{{count}} messages', { count: threads?.count, defaultValue_one: '{{count}} message' })
                    }
                </p>
                <div className="thread-panel__bar">
                    <Tooltip content={t('Mark all as read')}>
                        <Button
                            onClick={() => markAsRead({ threadIds: threads?.results.map((thread) => thread.id) })}
                            icon={<span className="material-icons">mark_email_read</span>}
                            variant="tertiary"
                            size="nano"
                            aria-label={t('Mark all as read')}
                        />
                    </Tooltip>
                    <DropdownMenu
                        isOpen={isDropdownOpen}
                        onOpenChange={setIsDropdownOpen}
                        options={[
                            {
                                label: t('Mark all as unread'),
                                icon: <span className="material-icons">mark_email_unread</span>,
                                callback: () => {
                                    markAsUnread({
                                        threadIds: threads?.results.map((thread) => thread.id),
                                        onSuccess: unselectThread
                                    })
                                },
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
