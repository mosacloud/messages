import { createContext, PropsWithChildren, useContext, useEffect, useMemo, useRef, useState } from "react";

type LayoutContextBase = {
    isLeftPanelOpen: boolean;
    setIsLeftPanelOpen: (open: boolean) => void;
    toggleLeftPanel: () => void;
    closeLeftPanel: () => void;
    openLeftPanel: () => void;
};

type LayoutDragContext = {
    isDragging: boolean;
    setIsDragging: (prevState: boolean) => void;
    dragAction: string | null;
    setDragAction: (action: string | null) => void;
    // Safari fallback: `e.shiftKey` on drag events is always `false` in
    // WebKit, so callers OR it with this getter. The ref is kept fresh by
    // a document-level keydown/keyup listener. Caveat: Safari also stops
    // firing keyboard events entirely while a drag is in progress, so on
    // Safari the returned value is effectively the Shift state at
    // `dragstart` time — pressing/releasing Shift mid-drag has no effect.
    // Chrome/Firefox populate `e.shiftKey` natively, so the getter is only
    // the safety net. Exposed as a getter (not state) to avoid rerendering
    // every consumer on each keystroke.
    getIsShiftHeld: () => boolean;
};

export type LayoutContextType = LayoutContextBase & Partial<LayoutDragContext>;

const LayoutContext = createContext<LayoutContextType | undefined>(undefined);

type LayoutProviderProps = PropsWithChildren<{
    draggable?: boolean;
}>;

export const LayoutProvider = ({ children, draggable = false }: LayoutProviderProps) => {
    const [isLeftPanelOpen, setIsLeftPanelOpen] = useState(false);
    const [isDragging, setIsDragging] = useState(false);
    const [dragAction, setDragAction] = useState<string | null>(null);
    const isShiftHeldRef = useRef(false);

    useEffect(() => {
        if (!draggable) return;
        const handler = (e: KeyboardEvent) => {
            isShiftHeldRef.current = e.shiftKey;
        };
        window.addEventListener('keydown', handler);
        window.addEventListener('keyup', handler);
        return () => {
            window.removeEventListener('keydown', handler);
            window.removeEventListener('keyup', handler);
        };
    }, [draggable]);

    const value = useMemo<LayoutContextType>(() => {
        const base: LayoutContextBase = {
            isLeftPanelOpen,
            setIsLeftPanelOpen,
            toggleLeftPanel: () => setIsLeftPanelOpen(!isLeftPanelOpen),
            closeLeftPanel: () => setIsLeftPanelOpen(false),
            openLeftPanel: () => setIsLeftPanelOpen(true),
        };
        if (!draggable) return base;
        return {
            ...base,
            isDragging,
            setIsDragging,
            dragAction,
            setDragAction,
            getIsShiftHeld: () => isShiftHeldRef.current,
        };
    }, [draggable, isLeftPanelOpen, isDragging, dragAction]);

    return <LayoutContext.Provider value={value}>{children}</LayoutContext.Provider>;
};

export const useLayoutContext = () => {
    const context = useContext(LayoutContext);
    if (!context) throw new Error("useLayoutContext must be used within a LayoutProvider");
    return context;
};

export const useLayoutDragContext = (): LayoutContextBase & LayoutDragContext => {
    const context = useLayoutContext();
    if (context.setIsDragging === undefined) {
        throw new Error("useLayoutDragContext requires a drag-enabled LayoutProvider");
    }
    return context as LayoutContextBase & LayoutDragContext;
};
