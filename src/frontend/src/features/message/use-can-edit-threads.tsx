import { useMemo } from "react";
import { useMailboxContext } from "@/features/providers/mailbox";

/**
 * Returns whether at least one of the given threads grants full edit
 * rights to the current user (`thread.abilities.edit === true`).
 *
 * Gates shared-state mutations (archive, spam, trash, auto-archive on
 * label drop). The backend enforces per-thread permissions and reports
 * the actual updated count in the toast — this hook only drives UI
 * affordances (disabled buttons, blocked drop zones).
 */
const useCanEditThreads = (threadIds: Set<string> | string[]): boolean => {
    const { threads } = useMailboxContext();
    return useMemo(() => {
        const ids = threadIds instanceof Set ? threadIds : new Set(threadIds);
        if (ids.size === 0) return false;
        return (threads?.results ?? []).some(
            (t) => ids.has(t.id) && t.abilities?.edit === true
        );
    }, [threadIds, threads?.results]);
};

export default useCanEditThreads;
