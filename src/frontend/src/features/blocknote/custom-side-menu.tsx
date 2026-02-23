import { SideMenuExtension } from '@blocknote/core/extensions';
import { MdDragIndicator } from 'react-icons/md';
import {
    DragHandleMenu,
    SideMenu,
    SideMenuController,
    useBlockNoteEditor,
    useComponentsContext,
    useDictionary,
    useExtension,
    useExtensionState,
} from '@blocknote/react';

const READ_ONLY_BLOCKS = new Set(['signature', 'quoted-message']);

/**
 * Custom DragHandleButton that works around a drag & drop issue on
 * Chromium / Safari where `dragend` fires immediately after `dragstart`,
 * effectively cancelling the drag before it begins.
 *
 * ## Root cause
 *
 * `blockDragStart()` dispatches a ProseMirror transaction (NodeSelection)
 * during the `dragstart` handler.  The selection change triggers BlockNote
 * extensions that listen to `onSelectionChange` (e.g. FormattingToolbar),
 * each calling `store.setState()`.  Via `useSyncExternalStore` these store
 * updates cause **synchronous React re-renders** — and any DOM mutation
 * during a `dragstart` handler makes Chromium / Safari cancel the drag.
 *
 * In a minimal BlockNote setup the React tree is simple enough that these
 * re-renders produce negligible DOM changes.  In our app the component
 * hierarchy is deeper (FormProvider, Field wrappers, flex-column-reverse
 * layout, watched form values…) so the re-renders cascade into visible
 * DOM mutations that trip the browser's drag-cancellation heuristic.
 *
 * ## Fix
 *
 * Calling `freezeMenu()` on `mousedown` (which fires **before**
 * `dragstart`) triggers the Tanstack Store update + React re-render early.
 * By the time `dragstart` fires the DOM is already stable, and the
 * `menuFrozen` flag short-circuits `updateStateFromMousePos()` so the
 * side-menu stays mounted throughout the drag lifecycle.
 *
 * ## Unfreeze paths
 *
 * - **Drag**: `onDragEnd` → `unfreezeMenu()`
 * - **Click (menu open)**: `onOpenChange(false)` → `unfreezeMenu()`
 */
const CustomDragHandleButton = () => {
    const Components = useComponentsContext()!;
    const dict = useDictionary();
    const sideMenu = useExtension(SideMenuExtension);
    const block = useExtensionState(SideMenuExtension, {
        selector: (state) => state?.block,
    });

    if (block === undefined) {
        return null;
    }

    return (
        <Components.Generic.Menu.Root
            onOpenChange={(open: boolean) => {
                if (open) {
                    sideMenu.freezeMenu();
                } else {
                    sideMenu.unfreezeMenu();
                }
            }}
            position={"left"}
        >
            <Components.Generic.Menu.Trigger>
                <div
                    onMouseDown={() => {
                        // Freeze BEFORE dragstart so the React re-render
                        // triggered by the store update completes before the
                        // browser captures the drag source element. Chromium
                        // and Safari cancel a drag when the DOM mutates during
                        // the dragstart handler.
                        sideMenu.freezeMenu();
                    }}
                >
                    <Components.SideMenu.Button
                        label={dict.side_menu.drag_handle_label}
                        draggable={true}
                        onDragStart={(e) => {
                            sideMenu.blockDragStart(e, block);
                        }}
                        onDragEnd={() => {
                            sideMenu.blockDragEnd();
                            sideMenu.unfreezeMenu();
                        }}
                        className={"bn-button"}
                        icon={<MdDragIndicator size={24} data-test="dragHandle" />}
                    />
                </div>
            </Components.Generic.Menu.Trigger>
            <DragHandleMenu />
        </Components.Generic.Menu.Root>
    );
};

const FilteredSideMenu = () => {
    const editor = useBlockNoteEditor();
    const block = useExtensionState(SideMenuExtension, {
        editor,
        selector: (state) => state?.block,
    });

    if (!block || READ_ONLY_BLOCKS.has(block.type)) {
        return null;
    }

    return (
        <SideMenu>
            <CustomDragHandleButton />
        </SideMenu>
    );
};

export const CustomSideMenuController = () => (
    <SideMenuController sideMenu={FilteredSideMenu} />
);
