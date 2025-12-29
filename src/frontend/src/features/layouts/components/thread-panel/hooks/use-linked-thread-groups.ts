import { useMemo } from "react";
import { Thread } from "@/features/api/gen";

export type MailboxInfo = {
    id: string;
    email: string;
    threadId: string; // The thread ID in this mailbox
};

export type ThreadGroup = {
    /** The primary thread (most recent or most messages) */
    primaryThread: Thread;
    /** All threads in this group (including primary) */
    threads: Thread[];
    /** Combined message count across all threads */
    totalMessages: number;
    /** Most recent messaged_at across all threads */
    latestDate: string | null;
    /** All unique mailboxes in this group with their IDs and associated thread */
    mailboxes: MailboxInfo[];
};

/**
 * Groups threads by their linked_thread_ids.
 * Threads that share the same conversation (via mime_id) are grouped together.
 *
 * @param threads - Array of threads to group
 * @param enabled - Whether grouping is enabled (e.g., only in unified view)
 * @returns Map of group key to ThreadGroup, plus ungrouped threads
 */
export const useLinkedThreadGroups = (
    threads: Thread[] | undefined,
    enabled: boolean = true
) => {
    return useMemo(() => {
        if (!threads?.length || !enabled) {
            return {
                groups: new Map<string, ThreadGroup>(),
                ungroupedThreads: threads ?? [],
                allItems: threads ?? [],
            };
        }

        // Build a union-find structure to group threads
        const threadIdToGroup = new Map<string, Set<string>>();
        const processedThreads = new Set<string>();

        // First pass: build groups based on linked_thread_ids
        for (const thread of threads) {
            const linkedIds = thread.linked_thread_ids ?? [];
            if (linkedIds.length === 0) {
                continue;
            }

            // Find or create the group for this thread
            let group = threadIdToGroup.get(thread.id);
            if (!group) {
                group = new Set([thread.id]);
                threadIdToGroup.set(thread.id, group);
            }

            // Add all linked threads to the same group
            for (const linkedId of linkedIds) {
                const existingGroup = threadIdToGroup.get(linkedId);
                if (existingGroup && existingGroup !== group) {
                    // Merge groups
                    for (const id of existingGroup) {
                        group.add(id);
                        threadIdToGroup.set(id, group);
                    }
                } else {
                    group.add(linkedId);
                    threadIdToGroup.set(linkedId, group);
                }
            }
        }

        // Second pass: build ThreadGroup objects
        const groups = new Map<string, ThreadGroup>();
        const ungroupedThreads: Thread[] = [];
        const groupedThreadIds = new Set<string>();

        for (const thread of threads) {
            if (processedThreads.has(thread.id)) {
                continue;
            }

            const group = threadIdToGroup.get(thread.id);
            if (!group || group.size <= 1) {
                // Not linked to any other thread in our list
                ungroupedThreads.push(thread);
                processedThreads.add(thread.id);
                continue;
            }

            // Find all threads in this group that exist in our threads array
            const groupThreads = threads.filter(t => group.has(t.id));

            // Only create a group if we have more than one thread
            if (groupThreads.length <= 1) {
                ungroupedThreads.push(thread);
                processedThreads.add(thread.id);
                continue;
            }

            // Sort by messaged_at descending to find primary
            groupThreads.sort((a, b) => {
                const dateA = a.messaged_at ? new Date(a.messaged_at).getTime() : 0;
                const dateB = b.messaged_at ? new Date(b.messaged_at).getTime() : 0;
                return dateB - dateA;
            });

            const primaryThread = groupThreads[0];
            const groupKey = Array.from(group).sort().join(',');

            // Calculate totals
            const totalMessages = groupThreads.reduce((sum, t) => {
                return sum + (t.messages?.length ?? 0);
            }, 0);

            const latestDate = groupThreads.reduce((latest, t) => {
                if (!t.messaged_at) return latest;
                if (!latest) return t.messaged_at;
                return new Date(t.messaged_at) > new Date(latest) ? t.messaged_at : latest;
            }, null as string | null);

            // Collect unique mailboxes with their IDs and thread associations
            const mailboxMap = new Map<string, MailboxInfo>();
            for (const t of groupThreads) {
                for (const access of t.accesses ?? []) {
                    if (access.mailbox?.id && access.mailbox?.email) {
                        // Use mailbox ID as key to avoid duplicates
                        if (!mailboxMap.has(access.mailbox.id)) {
                            mailboxMap.set(access.mailbox.id, {
                                id: access.mailbox.id,
                                email: access.mailbox.email,
                                threadId: t.id,
                            });
                        }
                    }
                }
            }

            groups.set(groupKey, {
                primaryThread,
                threads: groupThreads,
                totalMessages,
                latestDate,
                mailboxes: Array.from(mailboxMap.values()),
            });

            // Mark all threads in group as processed
            for (const t of groupThreads) {
                processedThreads.add(t.id);
                groupedThreadIds.add(t.id);
            }
        }

        // Build allItems: groups first (sorted by date), then ungrouped threads
        const sortedGroups = Array.from(groups.values()).sort((a, b) => {
            const dateA = a.latestDate ? new Date(a.latestDate).getTime() : 0;
            const dateB = b.latestDate ? new Date(b.latestDate).getTime() : 0;
            return dateB - dateA;
        });

        // Interleave groups and ungrouped threads by date
        const allItems: (ThreadGroup | Thread)[] = [];
        let groupIdx = 0;
        let ungroupedIdx = 0;

        while (groupIdx < sortedGroups.length || ungroupedIdx < ungroupedThreads.length) {
            const groupDate = sortedGroups[groupIdx]?.latestDate;
            const threadDate = ungroupedThreads[ungroupedIdx]?.messaged_at;

            const groupTime = groupDate ? new Date(groupDate).getTime() : 0;
            const threadTime = threadDate ? new Date(threadDate).getTime() : 0;

            if (groupIdx >= sortedGroups.length) {
                allItems.push(ungroupedThreads[ungroupedIdx++]);
            } else if (ungroupedIdx >= ungroupedThreads.length) {
                allItems.push(sortedGroups[groupIdx++]);
            } else if (groupTime >= threadTime) {
                allItems.push(sortedGroups[groupIdx++]);
            } else {
                allItems.push(ungroupedThreads[ungroupedIdx++]);
            }
        }

        return {
            groups,
            ungroupedThreads,
            allItems,
        };
    }, [threads, enabled]);
};

/**
 * Type guard to check if an item is a ThreadGroup
 */
export const isThreadGroup = (item: ThreadGroup | Thread): item is ThreadGroup => {
    return 'primaryThread' in item && 'threads' in item;
};
