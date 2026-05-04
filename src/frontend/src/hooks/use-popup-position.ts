import { RefObject, useLayoutEffect, useRef, useState } from "react";

/**
 * Computes and keeps in sync the fixed-position coordinates of a portaled popup
 * anchored to a trigger element. Recomputes on open, window resize, scroll (capture
 * phase, so scrollable ancestors are covered), and when the anchor itself resizes
 * — the latter via ResizeObserver, which prevents the popup from drifting when the
 * anchor's content changes (e.g. badges added/removed while the popup stays open).
 *
 * The `compute` callback receives the anchor's DOMRect and returns whatever shape
 * the caller needs (top/left, top/right, maxHeight, etc.), so positioning strategy
 * stays at the call site.
 *
 * @returns the computed position, or null before the first measurement.
 */
export const usePopupPosition = <P,>(
    anchorRef: RefObject<HTMLElement | null>,
    isOpen: boolean,
    compute: (rect: DOMRect) => P,
): P | null => {
    const [position, setPosition] = useState<P | null>(null);
    const computeRef = useRef(compute);
    computeRef.current = compute;

    useLayoutEffect(() => {
        if (!isOpen) return;
        const el = anchorRef.current;
        if (!el) return;

        const updatePosition = () => {
            setPosition(computeRef.current(el.getBoundingClientRect()));
        };

        updatePosition();
        window.addEventListener('resize', updatePosition);
        window.addEventListener('scroll', updatePosition, true);
        const observer = new ResizeObserver(updatePosition);
        observer.observe(el);

        return () => {
            window.removeEventListener('resize', updatePosition);
            window.removeEventListener('scroll', updatePosition, true);
            observer.disconnect();
        };
    }, [anchorRef, isOpen]);

    return position;
};
