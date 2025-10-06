import { ThreadsStatsRetrieve200, ThreadsStatsRetrieveStatsFields, useThreadsStatsRetrieve } from "@/features/api/gen"
import { useMailboxContext } from "@/features/providers/mailbox"
import clsx from "clsx"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { useMemo } from "react"
import { useLayoutContext } from "../../../main"
import { useTranslation } from "react-i18next"
import { Icon, IconType } from "@gouvfr-lasuite/ui-kit"
import i18n from "@/features/i18n/initI18n";

// @TODO: replace with real data when folder will be ready
type Folder = {
    id: string;
    name: string;
    icon: string;
    filter?: Record<string, string>;
}

export const MAILBOX_FOLDERS: Folder[] = [
    {
        id: "inbox",
        name: i18n.t("Inbox"),
        icon: "inbox",
        filter: {
            has_active: "1"
        },
    },
    {
        id: "all_messages",
        name: i18n.t("All messages"),
        icon: "folder",
        filter: {
            has_messages: "1"
        },
    },
    {
        id: "drafts",
        name: i18n.t("Drafts"),
        icon: "drafts",
        filter: {
            has_draft: "1",
        },
    },
    {
        id: "sent",
        name: i18n.t("Sent"),
        icon: "outbox",
        filter: {
            has_sender: "1"
        },
    },
    {
        id: "trash",
        name: i18n.t("Trash"),
        icon: "delete",
        filter: {
            has_trashed: "1",
        },
    },
    // {
    //     id: "spam",
    //     name: "folders.spam",
    //     icon: "report",
    //     filter: {
    //         is_spam: "1",
    //     },
    // },
    // {
    //     id: "archive",
    //     name: "folders.archive",
    //     icon: "inventory_2",
    //     filter: {
    //         has_archived: "1",
    //     },
    // },
]

export const MailboxList = () => {
    return (
        <div className="mailbox-list">
            {MAILBOX_FOLDERS.map((folder) => (
                <FolderItem
                    key={folder.icon}
                    folder={folder}
                />
            ))}
        </div>
    )
}

type FolderItemProps = {
    folder: Folder
}

const FolderItem = ({ folder }: FolderItemProps) => {
    const { t } = useTranslation();
    const { selectedMailbox } = useMailboxContext();
    const { closeLeftPanel } = useLayoutContext();
    const searchParams = useSearchParams()
    const queryParams = useMemo(() => {
        const params = new URLSearchParams(Object.entries(folder.filter || {}));
        return params.toString();
    }, [folder.filter]);
    const stats_fields = useMemo(() => {
        if (folder.filter?.has_draft === "1") return ThreadsStatsRetrieveStatsFields.all;
        return ThreadsStatsRetrieveStatsFields.all_unread;
    }, []);
    const { data } = useThreadsStatsRetrieve({
        mailbox_id: selectedMailbox?.id,
        stats_fields,
        ...folder.filter
    }, {
        query: {
            queryKey: ['threads', 'stats', selectedMailbox!.id, queryParams],
        }
    });

    const folderStats = data?.data as ThreadsStatsRetrieve200;

    const isActive = useMemo(() => {
        const folderFilter = Object.entries(folder.filter || {});
        if (folderFilter.length !== searchParams.size) return false;

        return folderFilter.every(([key, value]) => {
            return searchParams.get(key) === value;
        });
    }, [searchParams, folder.filter]);

    return (
        <Link
            href={`/mailbox/${selectedMailbox?.id}?${queryParams}`}
            onClick={closeLeftPanel}
            shallow={false}
            className={clsx("mailbox__item", {
                "mailbox__item--active": isActive
            })}
        >
            <p className="mailbox__item-label">
                <Icon name={folder.icon} type={IconType.OUTLINED} aria-hidden="true" />
                {t(folder.name)}
            </p>
            {(folderStats?.[stats_fields] ?? 0) > 0 && <span className="mailbox__item-counter">{folderStats[stats_fields]}</span>}
        </Link>
    )
}
