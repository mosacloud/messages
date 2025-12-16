import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { Thread } from "@/features/api/gen/models/thread";

interface UseThreadSelectionProps {
    threads: Thread[] | undefined;
    selectedThread?: Thread | null;
}

export const useThreadSelection = ({ threads, selectedThread }: UseThreadSelectionProps) => {
    const searchParams = useSearchParams();
    const [selectedThreadIds, setSelectedThreadIds] = useState<Set<string>>(new Set());
    const [isSelectionMode, setIsSelectionMode] = useState(false);
    const lastActiveIndexRef = useRef<number | null>(null);
    const anchorIndexRef = useRef<number | null>(null);
    const focusIndexRef = useRef<number | null>(null);

    const toggleThreadSelection = useCallback((
        threadId: string,
        index: number,
        shiftKey: boolean = false,
        ctrlKey: boolean = false,
        arrowUpKey?: 'up' | 'down'
    ) => {
        if (!threads) return;

        setSelectedThreadIds((prev) => {
            let newSet: Set<string>;

            if (shiftKey && arrowUpKey) {
                // Shift+Arrow key: macOS Finder-like behavior
                // Initialize anchor and focus if needed
                if (anchorIndexRef.current === null || focusIndexRef.current === null) {
                    // No anchor set: start from current item or selected thread
                    if (prev.size > 0) {
                        // Find the first selected item to use as anchor
                        const firstSelectedId = Array.from(prev)[0];
                        const firstSelectedIndex = threads.findIndex((t) => t.id === firstSelectedId);
                        anchorIndexRef.current = firstSelectedIndex;
                        focusIndexRef.current = firstSelectedIndex;
                    } else {
                        // No selection: use current index as both anchor and focus
                        anchorIndexRef.current = index;
                        focusIndexRef.current = index;
                    }
                }

                // Move focus based on arrow key
                let newFocusIndex = focusIndexRef.current;
                if (arrowUpKey === 'up' && newFocusIndex > 0) {
                    newFocusIndex = newFocusIndex - 1;
                } else if (arrowUpKey === 'down' && newFocusIndex < threads.length - 1) {
                    newFocusIndex = newFocusIndex + 1;
                }

                // Update focus
                focusIndexRef.current = newFocusIndex;

                // Select all items between anchor and focus (inclusive)
                const start = Math.min(anchorIndexRef.current, newFocusIndex);
                const end = Math.max(anchorIndexRef.current, newFocusIndex);
                const range = threads.slice(start, end + 1);
                newSet = new Set(range.map((thread) => thread.id));

                // Focus the element at the new focus index
                // This needs to happen after the render, so we'll do it in a setTimeout
                setTimeout(() => {
                    const threadItems = document.querySelectorAll('.thread-item');
                    if (threadItems[newFocusIndex]) {
                        (threadItems[newFocusIndex] as HTMLElement).focus();
                    }
                }, 0);
            }
            else if (shiftKey) {
                // Shift+Click: range selection
                // Determine the anchor index for range selection
                // Priority: 1) Last anchor (from normal click), 2) Active/opened thread, 3) First item
                let anchorIndex: number;

                // First, use the anchor if available
                if (lastActiveIndexRef.current !== null) {
                    anchorIndex = lastActiveIndexRef.current;
                } else {
                    // If no anchor, try to use the active thread index
                    if (selectedThread) {
                        const activeThreadIndex = threads.findIndex((t) => t.id === selectedThread.id);
                        if (activeThreadIndex !== -1) {
                            anchorIndex = activeThreadIndex;
                            // Set the anchor to the active thread for future shift-clicks
                            lastActiveIndexRef.current = activeThreadIndex;
                        } else {
                            // Fallback to first item if active thread not found in list
                            anchorIndex = 0;
                            lastActiveIndexRef.current = 0;
                        }
                    } else {
                        // No anchor and no active thread: select from first item to clicked item
                        anchorIndex = 0;
                        lastActiveIndexRef.current = 0;
                    }
                }

                // Update anchor and focus for shift+arrow to work correctly after shift+click
                anchorIndexRef.current = anchorIndex;
                focusIndexRef.current = index;

                // Range selection: select from anchor to current (replace previous selection)
                const start = Math.min(anchorIndex, index);
                const end = Math.max(anchorIndex, index);
                const range = threads.slice(start, end + 1);
                newSet = new Set(range.map((thread) => thread.id));
            } else if (ctrlKey) {
                // Ctrl/Cmd+Click: toggle individual without affecting others
                newSet = new Set(prev);
                if (newSet.has(threadId)) {
                    newSet.delete(threadId);
                } else {
                    newSet.add(threadId);
                }
                // Update focus but not anchor
                focusIndexRef.current = index;
                // Keep anchor as is for future shift+click operations
            } else {
                // Normal click: if already selected, unselect it; otherwise, clear others and select only this one
                if (prev.has(threadId)) {
                    // If already selected, just unselect it
                    newSet = new Set(prev);
                    newSet.delete(threadId);
                } else {
                    // Otherwise, clear all and select only this one
                    newSet = new Set([threadId]);
                }
                // Update anchor and focus on normal clicks
                lastActiveIndexRef.current = index;
                anchorIndexRef.current = index;
                focusIndexRef.current = index;
            }

            // Keep selection mode enabled when selecting; do not auto-disable when empty to allow manual mode
            if (newSet.size > 0) {
                setIsSelectionMode(true);
            }

            return newSet;
        });
    }, [threads, selectedThread]);

    const selectAllThreads = useCallback(() => {
        if (!threads) return;
        const allIds = new Set(threads.map((thread) => thread.id));
        setSelectedThreadIds(allIds);
        setIsSelectionMode(true);
    }, [threads]);

    const clearSelection = useCallback(() => {
        setSelectedThreadIds(new Set());
        lastActiveIndexRef.current = null;
        anchorIndexRef.current = null;
        focusIndexRef.current = null;
        setIsSelectionMode(false);
    }, []);

    const enableSelectionMode = useCallback(() => {
        setIsSelectionMode(true);
    }, []);

    const isAllSelected = useMemo(() => {
        if (!threads?.length) return false;
        return threads.every((thread) => selectedThreadIds.has(thread.id));
    }, [threads, selectedThreadIds]);

    const isSomeSelected = useMemo(() => {
        if (!threads?.length) return false;
        return threads.some((thread) => selectedThreadIds.has(thread.id));
    }, [threads, selectedThreadIds]);

    // Clear selection when threads or search params change
    useEffect(() => {
        setSelectedThreadIds(new Set());
        lastActiveIndexRef.current = null;
        anchorIndexRef.current = null;
        focusIndexRef.current = null;
        setIsSelectionMode(false);
    }, [searchParams]);

    // Keyboard controls
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
                // Ctrl+A or Cmd+A: select all threads
            // Check both 'a' and 'A' explicitly for Safari
            const isSelectAllShortcut = (e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'a');

            if (isSelectAllShortcut) {
                // Only handle if selection mode is active or focus is in thread panel
                const threadPanel = document.querySelector('.thread-panel');
                const isFocusInPanel = threadPanel && threadPanel.contains(document.activeElement);

                if (isSelectionMode || isFocusInPanel) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    selectAllThreads();
                    return;
                }
            }

            if (!isSelectionMode) return;

            // Escape: clear selection if selection mode is enabled
            if (e.key === 'Escape') {
                e.preventDefault();
                clearSelection();
                return;
            }
        };

        // Add listeners to both document and window for maximum Safari compatibility
        document.addEventListener('keydown', handleKeyDown, true);

        return () => {
            document.removeEventListener('keydown', handleKeyDown, true);
        };
    }, [selectedThreadIds.size, isSelectionMode, clearSelection, selectAllThreads]);

    return {
        selectedThreadIds,
        isSelectionMode,
        toggleThreadSelection,
        selectAllThreads,
        clearSelection,
        enableSelectionMode,
        isAllSelected,
        isSomeSelected,
    };
};
