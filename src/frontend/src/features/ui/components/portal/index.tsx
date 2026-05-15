import { ReactNode } from "react";
import { createPortal } from "react-dom";

export type PortalProps = {
    /** Defaults to `document.body`. */
    container?: HTMLElement;
    children: ReactNode;
};

/**
 * Render children into a different DOM subtree (default: `document.body`).
 * Useful to escape ancestor `overflow: hidden|auto` or stacking contexts —
 * tooltips, popovers, floating menus, drag previews.
 *
 * SSR-safe: renders nothing on the server (no document).
 */
export const Portal = ({ container, children }: PortalProps) => {
    if (typeof document === "undefined") return null;
    return createPortal(children, container ?? document.body);
};
