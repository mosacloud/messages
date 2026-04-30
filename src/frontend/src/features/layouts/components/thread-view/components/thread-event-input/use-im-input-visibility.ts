import { RefObject, useEffect, useRef, useState } from "react";

/**
 * Distance (px) from the bottom of the scroll container within which
 * the ThreadEventInput stays visible. Beyond this threshold, the input
 * slides out to avoid cluttering the reading area.
 */
const NEAR_BOTTOM_THRESHOLD = 150;

/**
 * Minimum downward scroll delta between two animation frames to
 * be considered a "fast scroll". When the user scrolls down quickly,
 * the ThreadEventInput is revealed even if the user hasn't reached the
 * bottom — signaling intent to interact.
 */
const FAST_SCROLL_DOWN_THRESHOLD = 35; // px
const FAST_SCROLL_TIMEOUT = 2000; // ms

/**
 * Minimum upward scroll distance (px) from the point where fast-scroll
 * was triggered before dismissing the input. Prevents tiny scroll
 * adjustments from hiding the input too eagerly.
 */
const SCROLL_UP_DISMISS_THRESHOLD = 100; // px

type UseIMInputVisibilityOptions = {
    containerRef: RefObject<HTMLDivElement | null>;
    threadId: string;
    isEditing: boolean;
    isMessageFormFocused: boolean;
};

/**
 * Manages the show/hide logic for the ThreadEventInput based on scroll
 * position and user interaction:
 * - visible when near the bottom of the scroll container
 * - visible during fast downward scrolling (signals intent to interact)
 * - visible when the input itself is focused or in edit mode
 * - hidden when the message reply form has focus
 */
export const useIMInputVisibility = ({
    containerRef,
    threadId,
    isEditing,
    isMessageFormFocused,
}: UseIMInputVisibilityOptions) => {
    const [isNearBottom, setIsNearBottom] = useState(false);
    const [isFocused, setIsFocused] = useState(false);
    const [isFastScrollingDown, setIsFastScrollingDown] = useState(false);
    const rafRef = useRef<number | null>(null);
    const lastScrollTopRef = useRef<number | null>(null);
    const fastScrollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const fastScrollOriginRef = useRef<number | null>(null);

    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;

        const updateNearBottom = () => {
            const distanceFromBottom =
                el.scrollHeight - el.scrollTop - el.clientHeight;
            setIsNearBottom(distanceFromBottom <= NEAR_BOTTOM_THRESHOLD);
        };

        updateNearBottom();

        const handleScroll = () => {
            if (rafRef.current !== null) return;
            rafRef.current = requestAnimationFrame(() => {
                rafRef.current = null;
                const scrollTop = el.scrollTop;
                updateNearBottom();

                // Detect fast downward scroll
                const prevScrollTop = lastScrollTopRef.current;
                lastScrollTopRef.current = scrollTop;
                if (prevScrollTop !== null) {
                    const delta = scrollTop - prevScrollTop;
                    if (delta >= FAST_SCROLL_DOWN_THRESHOLD) {
                        setIsFastScrollingDown(true);
                        fastScrollOriginRef.current = scrollTop;
                        if (fastScrollTimeoutRef.current !== null) {
                            clearTimeout(fastScrollTimeoutRef.current);
                        }
                        fastScrollTimeoutRef.current = setTimeout(() => {
                            fastScrollTimeoutRef.current = null;
                            fastScrollOriginRef.current = null;
                            setIsFastScrollingDown(false);
                        }, FAST_SCROLL_TIMEOUT);
                    } else if (
                        delta < 0 &&
                        fastScrollOriginRef.current !== null &&
                        fastScrollOriginRef.current - scrollTop >= SCROLL_UP_DISMISS_THRESHOLD
                    ) {
                        if (fastScrollTimeoutRef.current !== null) {
                            clearTimeout(fastScrollTimeoutRef.current);
                            fastScrollTimeoutRef.current = null;
                        }
                        fastScrollOriginRef.current = null;
                        setIsFastScrollingDown(false);
                    }
                }
            });
        };

        el.addEventListener("scroll", handleScroll, { passive: true });
        return () => {
            el.removeEventListener("scroll", handleScroll);
            if (rafRef.current !== null) {
                cancelAnimationFrame(rafRef.current);
                rafRef.current = null;
            }
            if (fastScrollTimeoutRef.current !== null) {
                clearTimeout(fastScrollTimeoutRef.current);
                fastScrollTimeoutRef.current = null;
            }
        };
    }, [threadId]);

    // Reset all scroll-related state on thread change
    useEffect(
        () => () => {
            setIsNearBottom(false);
            setIsFocused(false);
            setIsFastScrollingDown(false);
            lastScrollTopRef.current = null;
            fastScrollOriginRef.current = null;
        },
        [threadId],
    );

    const isVisible =
        isEditing ||
        isFocused ||
        (!isMessageFormFocused && (isNearBottom || isFastScrollingDown));

    return {
        isVisible,
        onFocusChange: setIsFocused,
    };
};
