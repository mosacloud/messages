import { Button, Tooltip, useModals } from "@gouvfr-lasuite/cunningham-react";
import { Icon, IconType } from "@gouvfr-lasuite/ui-kit";
import { forwardRef, useImperativeHandle, useMemo, useState } from "react";
import {
    ThreadAccessRoleChoices,
    ThreadAccessDetail,
    MailboxLight,
    ThreadEventTypeEnum,
    UserWithoutAbilities,
    useMailboxesSearchList,
    useThreadsAccessesCreate,
    useThreadsAccessesDestroy,
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
import { UpgradeMailboxRoleModal } from "./upgrade-mailbox-role-modal";

export type ThreadAccessesWidgetHandle = {
    open: () => void;
};

type ThreadAccessesWidgetProps = {
    accesses: readonly ThreadAccessDetail[];
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
    const [pendingUpgrade, setPendingUpgrade] = useState<{
        user: UserWithoutAbilities;
        access: ThreadAccessDetail;
    } | null>(null);
    const [isUpgrading, setIsUpgrading] = useState(false);
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

    useImperativeHandle(ref, () => ({
        open: () => setIsShareModalOpen(true),
    }), []);

    const { mutate: removeThreadAccess } = useThreadsAccessesDestroy({
        mutation: { onSuccess: () => invalidateThreadMessages() },
    });
    const { mutate: createThreadAccess } = useThreadsAccessesCreate({
        mutation: { onSuccess: () => invalidateThreadMessages() },
    });
    const { mutate: updateThreadAccess } = useThreadsAccessesUpdate({
        mutation: { onSuccess: () => invalidateThreadMessages() },
    });
    const { mutate: createThreadEvent } = useThreadsEventsCreate();

    const searchMailboxesQuery = useMailboxesSearchList(
        selectedMailbox?.id ?? "",
        { q: searchQuery },
        { query: { enabled: !!(selectedMailbox && searchQuery) } },
    );

    const getAccessUser = (mailbox: MailboxLight) => ({
        ...mailbox,
        full_name: mailbox.name,
    });

    const searchResults = searchMailboxesQuery.data?.data
        .filter((mailbox) => !accesses.some((a) => a.mailbox.id === mailbox.id))
        .map(getAccessUser) ?? [];

    const hasOnlyOneEditor = accesses.filter((a) => a.role === ThreadAccessRoleChoices.editor).length === 1;
    const canManageThreadAccess = useAbility(Abilities.CAN_MANAGE_THREAD_ACCESS, [selectedMailbox!, selectedThread!]);
    const isAssignmentContext = useIsSharedContext();

    const normalizedAccesses = accesses.map((access) => ({
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
            createThreadAccess({
                threadId: selectedThread!.id,
                data: {
                    thread: selectedThread!.id,
                    mailbox: mailboxId,
                    role: role as ThreadAccessRoleChoices,
                },
            });
        });
    };

    const handleUpdateAccess = (access: ThreadAccessDetail, role: string) => {
        updateThreadAccess({
            id: access.id,
            threadId: selectedThread!.id,
            data: {
                thread: selectedThread!.id,
                mailbox: access.mailbox.id,
                role: role as ThreadAccessRoleChoices,
            },
        });
    };

    const handleDeleteAccess = async (access: ThreadAccessDetail) => {
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
        removeThreadAccess({
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

    const dispatchAssignEvent = (user: UserWithoutAbilities) => {
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
        });
    };

    const handleAssignUser = (user: UserWithoutAbilities, access: ThreadAccessDetail) => {
        if (access.role === ThreadAccessRoleChoices.viewer) {
            setPendingUpgrade({ user, access });
            return;
        }
        dispatchAssignEvent(user);
    };

    const handleConfirmUpgrade = () => {
        if (!pendingUpgrade) return;
        const { user, access } = pendingUpgrade;
        setIsUpgrading(true);
        updateThreadAccess({
            id: access.id,
            threadId: selectedThread!.id,
            data: {
                thread: selectedThread!.id,
                mailbox: access.mailbox.id,
                role: ThreadAccessRoleChoices.editor,
            },
        }, {
            onSuccess: () => {
                dispatchAssignEvent(user);
                setPendingUpgrade(null);
                setIsUpgrading(false);
            },
            onError: () => {
                setIsUpgrading(false);
            },
        });
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
            <ShareModal<MailboxLight, MailboxLight, ThreadAccessDetail>
                modalTitle={isAssignmentContext ? t('Share and assign the thread') : t('Share the thread')}
                isOpen={isShareModalOpen}
                loading={searchMailboxesQuery.isLoading}
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
                membersTitle={(members) => {
                    const sharedCount = members.filter(
                        (m) => (m.users?.length ?? 0) > 1 || m.mailbox.is_identity === false,
                    ).length;
                    return t('Shared between {{count}} mailboxes, {{sharedCount}} of which are shared', {
                        count: members.length,
                        sharedCount,
                        defaultValue_one: 'Shared between {{count}} mailbox, {{sharedCount}} of which are shared',
                    });
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
                        onAssign={handleAssignUser}
                    />
                )}
                renderAccessRightExtras={(access) => {
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
                    return (
                        <Button
                            onClick={() => handleAssignUser(user, access)}
                            size="small"
                            variant="secondary"
                            className="share-modal-extensions__inline-assign"
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
            <UpgradeMailboxRoleModal
                isOpen={pendingUpgrade !== null}
                onClose={() => {
                    if (isUpgrading) return;
                    setPendingUpgrade(null);
                }}
                onConfirm={handleConfirmUpgrade}
                user={pendingUpgrade?.user ?? null}
                access={pendingUpgrade?.access ?? null}
                isPending={isUpgrading}
            />
        </>
    );
});
