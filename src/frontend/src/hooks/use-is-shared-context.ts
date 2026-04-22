import { useMailboxContext } from "@/features/providers/mailbox";

/**
 * True when the current thread/mailbox pair is collaborative: shared
 * mailbox (non-identity) or thread accessible from more than one mailbox.
 * Gates collaboration features (assignment CTAs, internal messages) that
 * have no purpose in a mono-user/mono-mailbox conversation.
 */
export const useIsSharedContext = (): boolean => {
    const { selectedMailbox, selectedThread } = useMailboxContext();
    return (
        selectedMailbox?.is_identity === false
        || (selectedThread?.accesses?.length ?? 0) > 1
    );
};
