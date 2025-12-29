import { createContext, PropsWithChildren, useContext, useEffect, useMemo } from "react";
import { Mailbox, MailboxRoleChoices, Message, messagesListResponse200, PaginatedThreadList, Thread, useLabelsList, useMailboxesList, useMessagesList, useThreadsListInfinite } from "../api/gen";
import { FetchStatus, QueryStatus, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/router";
import usePrevious from "@/hooks/use-previous";
import { useSearchParams } from "next/navigation";
import { MAILBOX_FOLDERS } from "../layouts/components/mailbox-panel/components/mailbox-list";
import { useDebounceCallback } from "@/hooks/use-debounce-callback";

type QueryState = {
    status: QueryStatus,
    fetchStatus: FetchStatus,
    isFetching: boolean;
    isLoading: boolean;
}

type PaginatedQueryState = QueryState & {
    isFetchingNextPage: boolean;
}

type MessageQueryInvalidationSource = {
    type: 'delete' | 'update';
    metadata: { ids?: Message['id'][], threadIds?: Thread['id'][] };
    payload?: Partial<Message>;
}

type MailboxContextType = {
    mailboxes: readonly Mailbox[] | null;
    threads: PaginatedThreadList | null;
    messages: readonly Message[] | null;
    selectedMailbox: Mailbox | null;
    selectedMailboxIds: string[];  // [] = all (unified), [id] = single, [id1, id2] = subset
    selectedThread: Thread | null;
    isUnifiedView: boolean;
    unselectThread: () => void;
    loadNextThreads: () => Promise<unknown>;
    invalidateThreadMessages: (source?: MessageQueryInvalidationSource) => Promise<void>;
    invalidateThreadsStats: () => Promise<void>;
    invalidateLabels: () => Promise<void>;
    refetchMailboxes: () => void;
    isPending: boolean;
    queryStates: {
        mailboxes: QueryState,
        threads: PaginatedQueryState,
        messages: QueryState,
    };
    error: {
        mailboxes: unknown | null;
        threads: unknown | null;
        messages: unknown | null;
    };
}

const MailboxContext = createContext<MailboxContextType>({
    mailboxes: null,
    threads: null,
    messages: null,
    selectedMailbox: null,
    selectedMailboxIds: [],
    selectedThread: null,
    isUnifiedView: false,
    loadNextThreads: async () => {},
    unselectThread: () => {},
    invalidateThreadMessages: async () => {},
    invalidateThreadsStats: async () => {},
    invalidateLabels: async () => {},
    refetchMailboxes: () => {},
    isPending: false,
    queryStates: {
        mailboxes: {
            status: 'pending',
            fetchStatus: 'idle',
            isFetching: false,
            isLoading: false,
        },
        threads: {
            status: 'pending',
            fetchStatus: 'idle',
            isFetching: false,
            isFetchingNextPage: false,
            isLoading: false,
        },
        messages: {
            status: 'pending',
            fetchStatus: 'idle',
            isFetching: false,
            isLoading: false,
        },
    },
    error: {
        mailboxes: null,
        threads: null,
        messages: null,
    },
});

/**
 * MailboxProvider is a context provider for the mailbox context.
 * It provides the mailboxes, threads and messages to its children
 * It also provides callbacks to select a mailbox, thread or message
 */
export const MailboxProvider = ({ children }: PropsWithChildren) => {
    const queryClient = useQueryClient();
    const router = useRouter();
    const searchParams = useSearchParams();
    const previousSearchParams = usePrevious(searchParams);
    const hasSearchParamsChanged = useMemo(() => {
        return previousSearchParams?.toString() !== searchParams.toString();
    }, [previousSearchParams, searchParams]);

    const mailboxQuery = useMailboxesList({
        query: {
            refetchInterval: 30 * 1000, // 30 seconds
            refetchOnWindowFocus: true,
        },
    });

    // Determine selected mailbox IDs from route
    // [] = unified (all mailboxes), [id] = single, [id1, id2] = subset
    const selectedMailboxIds = useMemo((): string[] => {
        const mailboxId = router.query.mailboxId as string | undefined;
        if (!mailboxId || mailboxId === 'unified') {
            return []; // Unified view - all mailboxes
        }
        return [mailboxId];
    }, [router.query.mailboxId]);

    // Unified view = no specific mailbox selected (empty array)
    const isUnifiedView = selectedMailboxIds.length === 0;

    // For backward compatibility and single-mailbox operations
    const selectedMailbox = useMemo(() => {
        if (!mailboxQuery.data?.data.length) return null;

        // In unified view or multi-select, don't select a single mailbox
        if (selectedMailboxIds.length !== 1) return null;

        const mailboxId = selectedMailboxIds[0];
        return mailboxQuery.data?.data.find((mailbox) => mailbox.id === mailboxId)
            ?? mailboxQuery.data.data.findLast(m => m.role === MailboxRoleChoices.admin)
            ?? mailboxQuery.data.data.findLast(m => m.role === MailboxRoleChoices.editor)
            ?? mailboxQuery.data.data.findLast(m => m.role === MailboxRoleChoices.sender)
            ?? mailboxQuery.data.data.findLast(m => m.role === MailboxRoleChoices.viewer)
            ?? mailboxQuery.data.data[mailboxQuery.data.data.length - 1]
    }, [selectedMailboxIds, mailboxQuery.data])

    const previousUnreadMessagesCount = usePrevious(selectedMailbox?.count_unread_messages);
    const threadQueryKey = useMemo(() => {
        const queryKey = ['threads', isUnifiedView ? 'unified' : selectedMailbox?.id];
        if (searchParams.get('search')) {
            return [...queryKey, 'search'];
        }
        // Exclude context param from query key (it's for thread view, not thread list)
        const paramsForKey = new URLSearchParams(searchParams);
        paramsForKey.delete('context');
        return [...queryKey, paramsForKey.toString()];
    }, [selectedMailbox?.id, searchParams, isUnifiedView]);

    // Build request params based on selectedMailboxIds
    // [] = no filter (all mailboxes), [id] = single mailbox, [id1, id2] = multiple (future)
    const threadRequestParams = useMemo(() => {
        const params = { ...(router.query as Record<string, string>) };
        // Remove route params and context (not API filters)
        delete params.mailboxId;
        delete params.threadId;
        delete params.context;
        // Only add mailbox_id filter when a single mailbox is selected
        if (selectedMailboxIds.length === 1) {
            params.mailbox_id = selectedMailboxIds[0];
        } else {
            // Unified view: include linked threads even if outside pagination
            params.include_linked = '1';
        }
        // TODO: Future - support multiple mailbox_ids for subset unification
        return params;
    }, [router.query, selectedMailboxIds]);

    const threadsQuery = useThreadsListInfinite(undefined, {
        query: {
            // Enable when we have mailboxes and either unified view or specific mailbox selected
            enabled: !!mailboxQuery.data?.data.length && (isUnifiedView || selectedMailboxIds.length > 0),
            initialPageParam: 1,
            queryKey: threadQueryKey,
            getNextPageParam: (lastPage, pages) => {
                return pages.length + 1;
            },
        },
        request: {
            params: threadRequestParams,
        }
    });

    /**
     * Flatten the threads paginated query to a single result array
     * Deduplicates threads that might appear in multiple pages via include_linked
     */
    const flattenThreads = useMemo(() => {
        const seenIds = new Set<string>();
        return threadsQuery.data?.pages.reduce((acc, page, index) => {
            const isLastPage = index === threadsQuery.data?.pages.length - 1;
            // Deduplicate: only add threads we haven't seen before
            for (const thread of page.data.results) {
                if (!seenIds.has(thread.id)) {
                    seenIds.add(thread.id);
                    acc.results.push(thread);
                }
            }
            if (isLastPage) {
                acc.count = page.data.count;
                acc.next = page.data.next;
                acc.previous = page.data.previous;
            }
            return acc;
            }, {results: [], count: 0, next: null, previous: null} as PaginatedThreadList);
    }, [threadsQuery.data?.pages]);

    const selectedThread = useMemo(() => {
        const threadId = router.query.threadId;
        return threadsQuery.data?.pages.flatMap((page) => page.data.results).find((thread) => thread.id === threadId) ?? null;
    }, [router.query.threadId, flattenThreads])
    const previousSelectedThreadMessagesCount = usePrevious(selectedThread?.messages.length);

    const messagesQuery = useMessagesList({
        query: {
            enabled: !!selectedThread,
            queryKey: ['messages', selectedThread?.id],
        },
        request: {
            params: {
                thread_id: selectedThread?.id ?? ''
            }
        }
    });

    const labelsQuery = useLabelsList({ mailbox_id: selectedMailbox?.id ?? '' }, {
        query: {
            enabled: !!selectedMailbox,
        },
    });


    const _updateThreadMessagesQueryData = (threadId: Thread['id'], source: MessageQueryInvalidationSource) => {
        queryClient.setQueryData(['messages', threadId], (oldData: messagesListResponse200 | undefined) => {
            if (!oldData?.data) return oldData;
            let newResults = [ ...oldData.data ];
            if (source.type === 'delete') {
                newResults = newResults.filter((message: Message) => {
                    if ((source.metadata.threadIds ?? []).includes(threadId)) return true;
                    return !(source.metadata.ids ?? []).includes(message.id);
                });
            } else if (source.type === 'update') {
                newResults = newResults.map((message: Message) => {
                    if (
                        (source.metadata.threadIds ?? []).includes(threadId)
                        || (source.metadata.ids ?? []).includes(message.id)
                    ) {
                        return { ...message, ...source.payload };
                    }
                    return message;
                });
            }

            return {...oldData, data: newResults};
        });
    }
    /**
     * Invalidate the threads and messages queries to refresh the data
     * If a source is provided, it could be used to update query cache from the source data
     */
    const invalidateThreadMessages = async (source?: MessageQueryInvalidationSource) => {
        await queryClient.invalidateQueries({ queryKey: ['threads', selectedMailbox?.id] });
        if (source && ((source.metadata.threadIds ?? []).length ?? 0) > 0) {
            source.metadata.threadIds!.forEach(threadId => {
                if (queryClient.getQueryState(['messages', threadId])) {
                    _updateThreadMessagesQueryData(threadId, source);
                }
            });
        }
        if (selectedThread) {
            await queryClient.invalidateQueries({ queryKey: ['messages', selectedThread.id] });
            if (source && ((source.metadata.ids ?? []).length ?? 0) > 0) {
                _updateThreadMessagesQueryData(selectedThread.id, source);
            }
        }
    }
    const resetSearchQueryDebounced = useDebounceCallback(() => {
        queryClient.resetQueries(
            { predicate: ({ queryKey}) => queryKey.includes('search') },
        );
    }, 500);

    const invalidateThreadsStats = async () => {
        await queryClient.invalidateQueries({
            queryKey: ['threads', 'stats', selectedMailbox?.id],
            predicate: ({ queryKey }) => !(queryKey[queryKey.length - 1] as string).startsWith('label_slug=')
        });
    }

    const invalidateLabels = async () => {
        await queryClient.invalidateQueries({ queryKey: labelsQuery.queryKey });
    }

    /**
     * Unselect the current thread and navigate to the mailbox page if needed
     */
    const unselectThread = () => {
        if (typeof window === 'undefined') return;

        const threadId = router.query.threadId as string | undefined;
        if (selectedMailbox && threadId && window.location.pathname.includes(threadId)) {
            router.push(`/mailbox/${selectedMailbox!.id}${window.location.search}`);
        }
    }

    const context = useMemo(() => ({
        mailboxes: mailboxQuery.data?.data ?? null,
        threads: flattenThreads ?? null,
        messages: messagesQuery.data?.data ?? null,
        selectedMailbox,
        selectedMailboxIds,
        selectedThread,
        isUnifiedView,
        unselectThread,
        loadNextThreads: threadsQuery.fetchNextPage,
        invalidateThreadMessages,
        invalidateThreadsStats,
        invalidateLabels,
        refetchMailboxes: mailboxQuery.refetch,
        isPending: mailboxQuery.isPending || threadsQuery.isPending || messagesQuery.isPending,
        queryStates: {
            mailboxes: {
                status: mailboxQuery.status,
                fetchStatus: mailboxQuery.fetchStatus,
                isFetching: mailboxQuery.isFetching,
                isLoading: mailboxQuery.isLoading,
            },
            threads: {
                status: threadsQuery.status,
                fetchStatus: threadsQuery.fetchStatus,
                isFetching: threadsQuery.isFetching,
                isFetchingNextPage: threadsQuery.isFetchingNextPage,
                isLoading: threadsQuery.isLoading,

            },
            messages: {
                status: messagesQuery.status,
                fetchStatus: messagesQuery.fetchStatus,
                isFetching: messagesQuery.isFetching,
                isLoading: messagesQuery.isLoading,
            },
        },
        error: {
            mailboxes: mailboxQuery.error,
            threads: threadsQuery.error,
            messages: messagesQuery.error,
        }
    }), [
        mailboxQuery,
        threadsQuery,
        messagesQuery,
        selectedMailbox,
        selectedMailboxIds,
        selectedThread,
        isUnifiedView,
    ]);

    useEffect(() => {
        // Don't redirect in unified view
        if (isUnifiedView) return;

        if (selectedMailbox) {
            if (router.pathname === '/' ||  (selectedMailbox.id !== router.query.mailboxId && !router.pathname.includes('new'))) {
                const defaultFolder = MAILBOX_FOLDERS()[0];
                const hash = window.location.hash;
                if (router.query.threadId) {
                    router.replace(`/mailbox/${selectedMailbox.id}/thread/${router.query.threadId}?${router.query.search}${hash}`);
                } else {
                    router.replace(`/mailbox/${selectedMailbox.id}?${new URLSearchParams(defaultFolder.filter).toString()}${hash}`);
                }
                invalidateThreadMessages();
            }
        }
    }, [selectedMailbox, isUnifiedView]);

    useEffect(() => {
        if (selectedMailbox && !selectedThread) {
            const threadId = router.query.threadId;
            const thread = flattenThreads?.results.find((thread) => thread.id === threadId);
            if (thread) {
                router.replace(`/mailbox/${selectedMailbox.id}/thread/${thread.id}?${searchParams}`);
            }
        }
    }, [flattenThreads]);

    // Invalidate the threads query to refresh the threads list when the unread messages count changes
    useEffect(() => {
        if (!selectedMailbox || previousUnreadMessagesCount === undefined) return;
        if (previousUnreadMessagesCount !== selectedMailbox.count_unread_messages) {
            invalidateThreadsStats();
            queryClient.invalidateQueries({ queryKey: ['threads', selectedMailbox?.id] });
        }
    }, [selectedMailbox?.count_unread_messages]);

    // Invalidate the thread messages query to refresh the thread messages when there is a new message
    useEffect(() => {
        if (!selectedThread || previousSelectedThreadMessagesCount === undefined) return;
        if (previousSelectedThreadMessagesCount < (selectedThread?.messages.length ?? 0)) {
            invalidateThreadMessages();
        }
    }, [selectedThread?.messages.length]);

    useEffect(() => {
        if (searchParams.get('search') !== previousSearchParams?.get('search')) {
            resetSearchQueryDebounced();
        }
        unselectThread();
    }, [hasSearchParamsChanged])

    return <MailboxContext.Provider value={context}>{children}</MailboxContext.Provider>
};

export const useMailboxContext = () => {
    const context = useContext(MailboxContext);
    if (!context) {
        throw new Error("`useMailboxContext` must be used within a children of `MailboxProvider`.");
    }
    return context;
}
