import { Thread } from "@/features/api/gen/models";
import { useTranslation } from "react-i18next";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMailboxContext } from "@/features/providers/mailbox";
import { useMemo } from "react";

type ThreadGroupOverviewProps = {
    thread: Thread;
};

export const ThreadGroupOverview = ({ thread }: ThreadGroupOverviewProps) => {
    const { t } = useTranslation();
    const searchParams = useSearchParams();
    const params = useParams<{ mailboxId: string; threadId: string }>();
    const { threads } = useMailboxContext();

    // Find all transitively linked threads from the current thread list
    const linkedThreads = useMemo(() => {
        if (!threads?.results) {
            return [thread];
        }

        // Build a set of all connected thread IDs using transitive closure
        const connectedIds = new Set<string>([thread.id]);
        let changed = true;

        while (changed) {
            changed = false;
            for (const t of threads.results) {
                // If this thread is in our connected set
                if (connectedIds.has(t.id)) {
                    // Add all its linked threads
                    for (const linkedId of t.linked_thread_ids ?? []) {
                        if (!connectedIds.has(linkedId)) {
                            connectedIds.add(linkedId);
                            changed = true;
                        }
                    }
                }
                // If this thread links to any thread in our connected set
                for (const linkedId of t.linked_thread_ids ?? []) {
                    if (connectedIds.has(linkedId) && !connectedIds.has(t.id)) {
                        connectedIds.add(t.id);
                        changed = true;
                    }
                }
            }
        }

        return threads.results.filter(t => connectedIds.has(t.id));
    }, [threads?.results, thread]);

    // Build URL with context param for each mailbox
    const buildThreadUrl = (mailboxId: string, threadId: string) => {
        const newParams = new URLSearchParams(searchParams);
        newParams.delete('context');
        newParams.set('context', mailboxId);
        return `/mailbox/${params?.mailboxId}/thread/${threadId}?${newParams}`;
    };

    // Group threads by mailbox
    const mailboxGroups = useMemo(() => {
        const groups = new Map<string, {
            mailboxId: string;
            email: string;
            threads: Array<{
                threadId: string;
                messageCount: number;
                summary: string;
                origin?: string;
            }>;
        }>();

        for (const t of linkedThreads) {
            for (const access of t.accesses ?? []) {
                if (access.mailbox?.id && access.mailbox?.email) {
                    const existing = groups.get(access.mailbox.id);
                    const threadEntry = {
                        threadId: t.id,
                        messageCount: t.messages?.length ?? 0,
                        summary: t.summary ?? '',
                        origin: access.origin,
                    };

                    if (existing) {
                        existing.threads.push(threadEntry);
                    } else {
                        groups.set(access.mailbox.id, {
                            mailboxId: access.mailbox.id,
                            email: access.mailbox.email,
                            threads: [threadEntry],
                        });
                    }
                }
            }
        }
        return Array.from(groups.values());
    }, [linkedThreads]);

    const totalThreads = mailboxGroups.reduce((sum, g) => sum + g.threads.length, 0);

    return (
        <div className="thread-group-overview">
            <div className="thread-group-overview__header">
                <Icon name="all_inbox" size={IconSize.LARGE} />
                <h2>{thread.subject || t('(no subject)')}</h2>
                <p className="thread-group-overview__subtitle">
                    {t('{{threadCount}} threads in {{mailboxCount}} mailboxes', {
                        threadCount: totalThreads,
                        mailboxCount: mailboxGroups.length
                    })}
                </p>
            </div>

            <div className="thread-group-overview__list">
                {mailboxGroups.map((group) => (
                    <div key={group.mailboxId} className="thread-group-overview__mailbox-group">
                        <div className="thread-group-overview__mailbox-header">
                            <Icon name="mail" size={IconSize.SMALL} />
                            <span className="thread-group-overview__mailbox-email">
                                {group.email}
                            </span>
                            <span className="thread-group-overview__thread-count">
                                {t('{{count}} threads', { count: group.threads.length })}
                            </span>
                        </div>
                        <div className="thread-group-overview__threads">
                            {group.threads.map((threadEntry) => (
                                <Link
                                    key={threadEntry.threadId}
                                    href={buildThreadUrl(group.mailboxId, threadEntry.threadId)}
                                    className="thread-group-overview__thread-item"
                                >
                                    <div className="thread-group-overview__thread-info">
                                        <span className="thread-group-overview__message-count">
                                            {t('{{count}} messages', { count: threadEntry.messageCount })}
                                        </span>
                                        {threadEntry.origin === 'shared' && (
                                            <span className="thread-group-overview__badge">
                                                {t('Shared')}
                                            </span>
                                        )}
                                    </div>
                                    {threadEntry.summary && (
                                        <p className="thread-group-overview__summary">
                                            {threadEntry.summary}
                                        </p>
                                    )}
                                </Link>
                            ))}
                        </div>
                    </div>
                ))}
            </div>

            <p className="thread-group-overview__hint">
                {t('Select a thread to view and reply to messages')}
            </p>
        </div>
    );
};
