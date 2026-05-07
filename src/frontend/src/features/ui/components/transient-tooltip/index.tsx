import { ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Portal } from "@/features/ui/components/portal";

const DEFAULT_DURATION_MS = 2000;

export type TransientTooltipPlacement = "top" | "bottom";

export type TransientTooltipProps = {
    message: string | null;
    onHide: () => void;
    duration?: number;
    placement?: TransientTooltipPlacement;
    children: ReactNode;
};

type Position = { top: number; left: number };

/**
 * Transient tooltip
 * Rendered through a portal so it can escape ancestor
 * `overflow: hidden|auto` (e.g. app-level layout clipping).
 */
export const TransientTooltip = ({
    message,
    onHide,
    duration = DEFAULT_DURATION_MS,
    placement = "bottom",
    children,
}: TransientTooltipProps) => {
    const wrapperRef = useRef<HTMLSpanElement | null>(null);
    const [position, setPosition] = useState<Position | null>(null);
    const [internalMessage, setInternalMessage] = useState<string | null>(null);
    const [isExiting, setIsExiting] = useState(false);

    // Delayed-unmount pattern: when the parent clears `message`, we keep the
    // bubble mounted under `c__tooltip--exiting` so its exit animation can
    // play. The real unmount happens in the animated node's `onAnimationEnd`
    // below — that fires exactly when Cunningham's `slide` keyframe completes,
    // so we don't have to mirror its duration in JS.
    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        if (message) {
            setInternalMessage(message);
            setIsExiting(false);
            return;
        }
        if (!internalMessage || isExiting) return;
        setIsExiting(true);
    }, [message, internalMessage, isExiting]);
    /* eslint-enable react-hooks/set-state-in-effect */

    useLayoutEffect(() => {
        if (!internalMessage) return;
        const updatePosition = () => {
            const rect = wrapperRef.current?.getBoundingClientRect();
            if (!rect) return;
            setPosition({
                top: placement === "bottom" ? rect.bottom : rect.top,
                left: rect.left + rect.width / 2,
            });
        };
        updatePosition();
        window.addEventListener("resize", updatePosition);
        return () => window.removeEventListener("resize", updatePosition);
    }, [internalMessage, placement]);

    useEffect(() => {
        if (!message) return;
        const timer = window.setTimeout(onHide, duration);
        return () => window.clearTimeout(timer);
    }, [message, duration, onHide]);

    return (
        <span ref={wrapperRef} className="transient-tooltip__wrapper">
            {children}
            {internalMessage && position && (
                <Portal>
                    <span
                        className={`transient-tooltip transient-tooltip--${placement}`}
                        style={{ top: position.top, left: position.left }}
                    >
                        <span
                            key={isExiting ? "exit" : "enter"}
                            className={`c__tooltip c__tooltip--${isExiting ? "exiting" : "entering"}`}
                            data-placement={placement}
                            role="status"
                            aria-live="polite"
                            onAnimationEnd={isExiting ? () => {
                                setInternalMessage(null);
                                setIsExiting(false);
                            } : undefined}
                        >
                            <span className="c__tooltip__content">{internalMessage}</span>
                        </span>
                    </span>
                </Portal>
            )}
        </span>
    );
};
