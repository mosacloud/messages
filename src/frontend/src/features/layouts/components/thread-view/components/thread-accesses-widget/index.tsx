import { Button, Tooltip, useModals } from "@gouvfr-lasuite/cunningham-react";
import { Icon, IconType, Spinner } from "@gouvfr-lasuite/ui-kit";
import { useQueryClient } from "@tanstack/react-query";
import { forwardRef, useImperativeHandle, useMemo, useState } from "react";
import {
    ThreadAccess,
    ThreadAccessRoleChoices,
    ThreadAccessDetail,
    MailboxLight,
    ThreadEventTypeEnum,
    UserWithoutAbilities,
    getThreadsAccessesListQueryKey,
    threadsAccessesListResponse,
    useMailboxesSearchList,
    useThreadsAccessesCreate,
    useThreadsAccessesDestroy,
    useThreadsAccessesList,
    useThreadsAccessesUpdate,
    useThreadsEventsCreate,
} from "@/features/api/gen";
import { useMailboxContext } from "@/features/providers/mailbox";
import { useTranslation } from "react-i18next";
import { addToast, ToasterItem } from "@/features/ui/components/toaster";
import useAbility, { Abilities } from "@/hooks/use-ability";
import { useIsSharedContext } from "@/hooks/use-is-shared-context";
import { useAssignedUsers } from "@/features/message/use-assigned-users";
import { AssignedUsersSection, AccessUsersList, ShareModal } from "../share-modal-extensions";

export type ThreadAccessesWidgetHandle = {
    open: () => void;
};

type ThreadAccessesWidgetProps = {
    accesses: readonly ThreadAccessDetail[];
};

/**
 * Display shape consumed by the ShareModal: `accesses` from Thread (nested
 * mailbox for rendering) joined with `users` from the `/accesses/` endpoint.
 * The join is required because `/accesses/` returns the mailbox as a flat FK
 * UUID — it's the authoritative source for `users`, but Thread.accesses
 * remains the source for mailbox display info.
 */
type EnrichedAccess = ThreadAccessDetail & {
    users: readonly UserWithoutAbilities[];
};

/**
 * Lists thread accesses and lets users manage sharing + per-user assignment.
 * Exposes an `open()` handle so the `AssigneesWidget` (rendered inside
 * `ThreadActionBar`) can reuse the exact same modal without duplicating state.
 *
 * The `ShareModal` from `@gouvfr-lasuite/ui-kit` is reused as-is for visual
 * consistency; assignment affordances are injected through its extension
 * points (`children` for the "assigned users" section, `accessRoleTopMessage`
 * returning a ReactNode for the per-mailbox user list).
 */
export const ThreadAccessesWidget = forwardRef<ThreadAccessesWidgetHandle, ThreadAccessesWidgetProps>(
    function ThreadAccessesWidget({ accesses }, ref) {
    const { t } = useTranslation();
    const [isShareModalOpen, setIsShareModalOpen] = useState(false);
    const [searchQuery, setSearchQuery] = useState("");
    const [assigningUserId, setAssigningUserId] = useState<string | null>(null);
    const {
        selectedMailbox,
        selectedThread,
        invalidateThreadMessages,
        invalidateThreadEvents,
        invalidateThreadsStats,
        unselectThread,
    } = useMailboxContext();
    const modals = useModals();
    const assignedUsers = useAssignedUsers();
    const queryClient = useQueryClient();

    useImperativeHandle(ref, () => ({
        open: () => setIsShareModalOpen(true),
    }), []);

    // Any mutation on thread accesses (add/update/remove member) also
    // impacts the thread messages (roles gate UI abilities), hence the
    // shared invalidation below.
    //
    // For the accesses list itself we prefer a targeted cache patch on
    // success rather than a refetch: the backend response already contains
    // the new/updated row, so we apply it directly to skip a round-trip
    // that would otherwise leave the select showing the old value
    // between mutation success and refetch completion. Create is the only
    // case that still triggers a refetch — the response lacks the
    // per-mailbox `users` list required by the modal.
    const patchAccessesCache = (
        updater: (prev: ThreadAccess[]) => ThreadAccess[],
    ) => {
        if (!selectedThread?.id) return;
        queryClient.setQueryData<threadsAccessesListResponse>(
            getThreadsAccessesListQueryKey(selectedThread.id),
            (old) => (old ? { ...old, data: updater(old.data) } : old),
        );
    };

    const removeMutation = useThreadsAccessesDestroy({
        mutation: {
            onSuccess: (_data, vars) => {
                invalidateThreadMessages();
                patchAccessesCache((prev) => prev.filter((a) => a.id !== vars.id));
            },
        },
    });
    const createMutation = useThreadsAccessesCreate({
        mutation: {
            onSuccess: () => {
                invalidateThreadMessages();
                if (selectedThread?.id) {
                    queryClient.invalidateQueries({
                        queryKey: getThreadsAccessesListQueryKey(selectedThread.id),
                    });
                }
            },
        },
    });
    const updateMutation = useThreadsAccessesUpdate({
        mutation: {
            onSuccess: (data) => {
                invalidateThreadMessages();
                patchAccessesCache((prev) =>
                    prev.map((a) =>
                        a.id === data.data.id ? { ...a, role: data.data.role } : a,
                    ),
                );
            },
        },
    });
    const { mutate: createThreadEvent } = useThreadsEventsCreate();

    // Per-row pending state: while a mutation is in flight for a given
    // access, the modal shows a spinner next to that row so the user
    // knows their click registered.
    const isAccessPending = (accessId: string) =>
        (updateMutation.isPending && updateMutation.variables?.id === accessId) ||
        (removeMutation.isPending && removeMutation.variables?.id === accessId);
    const isMailboxPending = (mailboxId: string) =>
        createMutation.isPending &&
        createMutation.variables?.data.mailbox === mailboxId;

    const searchMailboxesQuery = useMailboxesSearchList(
        selectedMailbox?.id ?? "",
        { q: searchQuery },
        { query: { enabled: !!(selectedMailbox && searchQuery) } },
    );

    const hasOnlyOneEditor = accesses.filter((a) => a.role === ThreadAccessRoleChoices.editor).length === 1;
    const canManageThreadAccess = useAbility(Abilities.CAN_MANAGE_THREAD_ACCESS, [selectedMailbox!, selectedThread!]);
    const isAssignmentContext = useIsSharedContext();

    const threadAccessesQuery = useThreadsAccessesList(
        selectedThread?.id ?? "",
        undefined,
        {
            query: {
                enabled:
                    !!selectedThread?.id && isShareModalOpen && canManageThreadAccess,
            },
        },
    );
    // Join Thread.accesses (nested mailbox, no users) with /accesses/
    // (users per access). The endpoint is gated by manage rights; viewers
    // get nothing from /accesses/ and fall back to empty users arrays so
    // the modal still renders mailbox rows without the assignable-user
    // sub-list.
    const usersByAccessId = useMemo(
        () =>
            new Map(
                (threadAccessesQuery.data?.data ?? []).map((a) => [a.id, a.users]),
            ),
        [threadAccessesQuery.data?.data],
    );
    const enrichedAccesses: readonly EnrichedAccess[] = accesses.map((access) => ({
        ...access,
        users: usersByAccessId.get(access.id) ?? [],
    }));

    const getAccessUser = (mailbox: MailboxLight) => ({
        ...mailbox,
        full_name: mailbox.name,
    });

    const searchResults = searchMailboxesQuery.data?.data
        .filter((mailbox) => !accesses.some((a) => a.mailbox.id === mailbox.id))
        .map(getAccessUser) ?? [];

    const normalizedAccesses = enrichedAccesses.map((access) => ({
        ...access,
        user: getAccessUser(access.mailbox),
        can_delete: canManageThreadAccess && accesses.length > 1 && (!hasOnlyOneEditor || access.role !== ThreadAccessRoleChoices.editor),
    }));

    const assignedUserIds = useMemo(
        () => new Set(assignedUsers.map((u) => u.id)),
        [assignedUsers],
    );

    const accessRoleOptions = (isDisabled?: boolean) =>
        Object.values(ThreadAccessRoleChoices).map((role) => ({
            label: t(`thread_roles_${role}`, { ns: 'roles' }),
            value: role,
            isDisabled: isDisabled ?? (hasOnlyOneEditor && role !== ThreadAccessRoleChoices.editor),
        }));

    const handleCreateAccesses = (mailboxes: MailboxLight[], role: string) => {
        const mailboxIds = [...new Set(mailboxes.map((m) => m.id))];
        mailboxIds.forEach((mailboxId) => {
            createMutation.mutate({
                threadId: selectedThread!.id,
                data: {
                    thread: selectedThread!.id,
                    mailbox: mailboxId,
                    role: role as ThreadAccessRoleChoices,
                },
            });
        });
    };

    const handleUpdateAccess = (access: EnrichedAccess, role: string) => {
        updateMutation.mutate({
            id: access.id,
            threadId: selectedThread!.id,
            data: {
                thread: selectedThread!.id,
                mailbox: access.mailbox.id,
                role: role as ThreadAccessRoleChoices,
            },
        });
    };

    const handleDeleteAccess = async (access: EnrichedAccess) => {
        if (hasOnlyOneEditor && access.role === ThreadAccessRoleChoices.editor) {
            addToast(
                <ToasterItem type="error">
                    <p>{t('You cannot delete the last editor of this thread')}</p>
                </ToasterItem>,
                { toastId: "last-editor-deletion-forbidden", autoClose: 3000 },
            );
            return;
        }
        const isSelfRemoval = access.mailbox.id === selectedMailbox?.id;
        const decision = await modals.deleteConfirmationModal({
            title: isSelfRemoval ? t('Leave this thread?') : t('Remove access?'),
            children: isSelfRemoval
                ? t(
                    'You and all users with access to the mailbox "{{mailboxName}}" will no longer see this thread.',
                    { mailboxName: access.mailbox.email },
                )
                : t(
                    'All users with access to the mailbox "{{mailboxName}}" will no longer see this thread.',
                    { mailboxName: access.mailbox.email },
                ),
        });
        if (decision !== 'delete') return;
        removeMutation.mutate({
            id: access.id,
            threadId: selectedThread!.id,
        }, {
            onSuccess: () => {
                addToast(
                    <ToasterItem>
                        <p>{t('Thread access removed')}</p>
                    </ToasterItem>,
                );
                if (isSelfRemoval) {
                    setIsShareModalOpen(false);
                    invalidateThreadMessages({
                        type: 'delete',
                        metadata: { threadIds: [selectedThread!.id] },
                    });
                    invalidateThreadsStats();
                    unselectThread();
                }
            },
        });
    };

    const dispatchAssignEvent = (
        user: UserWithoutAbilities,
        options?: { onSettled?: () => void },
    ) => {
        createThreadEvent({
            threadId: selectedThread!.id,
            data: {
                type: ThreadEventTypeEnum.assign,
                data: {
                    assignees: [{ id: user.id, name: user.full_name || user.email || "" }],
                },
            },
        }, {
            onSuccess: async () => {
                await invalidateThreadEvents();
                await invalidateThreadsStats();
            },
            onSettled: () => options?.onSettled?.(),
        });
    };

    const handleAssignUser = async (user: UserWithoutAbilities, access: EnrichedAccess) => {
        if (access.role === ThreadAccessRoleChoices.viewer) {
            const decision = await modals.confirmationModal({
                title: <span className="c__modal__text--centered">{t('Grant editor access to the thread?')}</span>,
                children: (
                    <span className="c__modal__text--centered">
                        {t(
                            'The mailbox "{{mailbox}}" currently has read-only access on this thread. To assign {{user}} to it, edit permissions must be granted to this mailbox.',
                            { mailbox: access.mailbox.email, user: user.full_name || user.email || "" },
                        )}
                    </span>
                ),
            });
            if (decision !== 'yes') return;
            setAssigningUserId(user.id);
            try {
                await updateMutation.mutateAsync({
                    id: access.id,
                    threadId: selectedThread!.id,
                    data: {
                        thread: selectedThread!.id,
                        mailbox: access.mailbox.id,
                        role: ThreadAccessRoleChoices.editor,
                    },
                });
            } catch {
                setAssigningUserId(null);
                return;
            }
        } else {
            setAssigningUserId(user.id);
        }
        dispatchAssignEvent(user, { onSettled: () => setAssigningUserId(null) });
    };

    const handleUnassignUser = (userId: string) => {
        const target = assignedUsers.find((u) => u.id === userId);
        if (!target) return;
        createThreadEvent({
            threadId: selectedThread!.id,
            data: {
                type: ThreadEventTypeEnum.unassign,
                data: {
                    assignees: [{ id: target.id, name: target.name }],
                },
            },
        }, {
            onSuccess: async () => {
                await invalidateThreadEvents();
                await invalidateThreadsStats();
            },
        });
    };

    return (
        <>
            <Tooltip content={t('See members of this thread ({{count}} members)', { count: accesses.length })}>
                <Button
                    variant="tertiary"
                    size="nano"
                    aria-label={t('See members of this thread ({{count}} members)', { count: accesses.length })}
                    className="thread-accesses-widget"
                    onClick={() => setIsShareModalOpen(true)}
                    icon={<Icon name="group" type={IconType.FILLED} />}
                >
                    {accesses.length}
                </Button>
            </Tooltip>
            <ShareModal<MailboxLight, MailboxLight, EnrichedAccess>
                modalTitle={isAssignmentContext ? t('Share and assign the thread') : t('Share the thread')}
                isOpen={isShareModalOpen}
                loading={searchMailboxesQuery.isLoading || threadAccessesQuery.isLoading}
                canUpdate={canManageThreadAccess}
                onClose={() => setIsShareModalOpen(false)}
                invitationRoles={accessRoleOptions(false)}
                getAccessRoles={() => accessRoleOptions()}
                onInviteUser={handleCreateAccesses}
                onUpdateAccess={handleUpdateAccess}
                onDeleteAccess={accesses.length > 1 ? handleDeleteAccess : undefined}
                onSearchUsers={setSearchQuery}
                searchUsersResult={searchResults}
                accesses={normalizedAccesses}
                allowInvitation={false}
                membersTitle={(members) => {
                    const sharedCount = members.filter(
                        (m) => (m.users?.length ?? 0) > 1 || m.mailbox.is_identity === false,
                    ).length;
                    const total = t('Shared between {{count}} mailboxes', {
                        count: members.length,
                        defaultValue_one: 'Shared between {{count}} mailbox',
                    });
                    if (sharedCount === 0) {
                        return total;
                    }
                    const shared = t('{{count}} of which are shared', {
                        count: sharedCount,
                        defaultValue: ', {{count}} of which are shared',
                        defaultValue_one: ', {{count}} of which is shared',
                    });
                    return `${total}${shared}`;
                }}
                accessRoleTopMessage={(access) => {
                    if (hasOnlyOneEditor && access.role === ThreadAccessRoleChoices.editor) {
                        return t('You are the last editor of this thread, you cannot therefore modify your access.');
                    }
                    return undefined;
                }}
                renderAccessFooter={(access) => (
                    <AccessUsersList
                        access={access}
                        assignedUserIds={assignedUserIds}
                        canAssign={canManageThreadAccess && isAssignmentContext}
                        assigningUserId={assigningUserId}
                        onAssign={handleAssignUser}
                    />
                )}
                renderAccessRightExtras={(access) => {
                    // Show an inline spinner when a mutation is in flight
                    // on this specific row (role change or removal) — the
                    // ShareModal's own select can't convey "pending" state.
                    if (isAccessPending(access.id) || isMailboxPending(access.mailbox.id)) {
                        return <Spinner size="sm" />;
                    }
                    // Identity mailboxes with a single user collapse the
                    // users sub-list into an inline "Assign" CTA on the row
                    // itself. A mailbox is "shared" when is_identity is
                    // false OR it hosts more than one user — those cases
                    // fall through to AccessUsersList below.
                    if (!access.users || access.users.length !== 1) return null;
                    if (access.mailbox.is_identity === false) return null;
                    if (!canManageThreadAccess) return null;
                    if (!isAssignmentContext) return null;
                    const user = access.users[0];
                    if (assignedUserIds.has(user.id)) return null;
                    const isAssigning = assigningUserId === user.id;
                    return (
                        <Button
                            onClick={() => handleAssignUser(user, access)}
                            size="small"
                            variant="secondary"
                            className="share-modal-extensions__inline-assign"
                            disabled={isAssigning || assigningUserId !== null}
                            icon={isAssigning ? <Spinner size="sm" /> : undefined}
                        >
                            {t('Assign')}
                        </Button>
                    );
                }}
                outsideSearchContent={(
                    <div className="share-modal-extensions__footer">
                        <Button onClick={() => setIsShareModalOpen(false)}>
                            {t('OK')}
                        </Button>
                    </div>
                )}
            >
                {isAssignmentContext && (
                    <AssignedUsersSection
                        assignedUsers={assignedUsers}
                        canUpdate={canManageThreadAccess}
                        onUnassign={handleUnassignUser}
                    />
                )}
            </ShareModal>
        </>
    );
});
