import { Extension } from '@tiptap/core';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { TextSelection } from '@tiptap/pm/state';
import { EditorView } from '@tiptap/pm/view';

const FOOTER_BLOCKS = ['signature', 'quoted-message'];

/**
 * Returns the position where a trailing block should be inserted and whether
 * insertion is needed. When footer blocks exist, the position is just before
 * them; otherwise it is at the end of the document.
 * Returns null if the document structure is invalid.
 */
const getTrailingBlockInfo = (view: EditorView) => {
    const { doc } = view.state;
    const rootBlockGroup = doc.firstChild;
    if (!rootBlockGroup || rootBlockGroup.type.name !== 'blockGroup') {
        return null;
    }

    let firstFooterIndex = -1;
    let lastBlockPosition = 1; // after root blockGroup opening
    for (let i = 0; i < rootBlockGroup.childCount; i++) {
        const blockContainer = rootBlockGroup.child(i);
        const contentNode = blockContainer.firstChild;
        if (
            contentNode &&
            FOOTER_BLOCKS.includes(contentNode.type.name)
        ) {
            firstFooterIndex = i;
            break;
        }
        lastBlockPosition += blockContainer.nodeSize;
    }

    // The last editable block is the one just before footer blocks, or the very last block
    const effectiveLastIndex = firstFooterIndex >= 0
        ? firstFooterIndex - 1
        : rootBlockGroup.childCount - 1;

    let needsCreateEmptyParagraph = true;
    if (effectiveLastIndex >= 0) {
        const lastBlock = rootBlockGroup.child(effectiveLastIndex);
        const lastContentNode = lastBlock.firstChild;
        if (lastContentNode && lastContentNode.type.spec.content === 'inline*') {
            needsCreateEmptyParagraph = false;
        }
    }

    return { lastBlockPosition, needsCreateEmptyParagraph };
};

/**
 * A TipTap extension that creates an empty paragraph before footer blocks
 * when the user clicks below editable content.
 *
 * Unlike BlockNote's built-in trailingBlock which always keeps an empty
 * block at the end, this only creates one on demand when the user clicks
 * in the "dead zone" below editable blocks.
 *
 * It also ensures there is always at least one editable block when the
 * document only contains special blocks.
 */
export const SmartTrailingBlock = Extension.create({
    name: 'smartTrailingBlock',

    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('smartTrailingBlock'),
                props: {
                    handleDOMEvents: {
                        click: (view, event) => {
                            const info = getTrailingBlockInfo(view);
                            if (!info) return false;

                            // Check where the click resolved to in the document
                            const coords = { left: event.clientX, top: event.clientY };
                            const posResult = view.posAtCoords(coords);

                            // Only handle clicks in the footer blocks area or empty padding below
                            if (posResult && posResult.pos < info.lastBlockPosition) return false;

                            if (info.needsCreateEmptyParagraph) {
                                const { schema, tr } = view.state;
                                const blockContainerType = schema.nodes['blockContainer'];
                                const paragraphType = schema.nodes['paragraph'];
                                if (!blockContainerType || !paragraphType) return false;

                                tr.insert(
                                    info.lastBlockPosition,
                                    blockContainerType.create(null, paragraphType.create()),
                                );
                                // Place cursor inside the new empty paragraph
                                // lastBlockPosition + 1 = inside blockContainer, + 1 = inside paragraph
                                tr.setSelection(TextSelection.create(tr.doc, info.lastBlockPosition + 2));
                                view.dispatch(tr);
                            }

                            view.focus();
                            return true;
                        },
                    },
                },
                appendTransaction: (transactions, _oldState, newState) => {
                    if (!transactions.some((tr) => tr.docChanged)) {
                        return null;
                    }

                    const { doc, tr, schema } = newState;
                    const rootBlockGroup = doc.firstChild;
                    if (
                        !rootBlockGroup ||
                        rootBlockGroup.type.name !== 'blockGroup'
                    ) {
                        return null;
                    }

                    // Only auto-insert when ALL blocks are footer blocks (no editable content at all)
                    for (let i = 0; i < rootBlockGroup.childCount; i++) {
                        const contentNode = rootBlockGroup.child(i).firstChild;
                        if (
                            !contentNode ||
                            !FOOTER_BLOCKS.includes(contentNode.type.name)
                        ) {
                            return null;
                        }
                    }

                    const blockContainerType = schema.nodes['blockContainer'];
                    const paragraphType = schema.nodes['paragraph'];
                    if (!blockContainerType || !paragraphType) return null;

                    return tr.insert(
                        1,
                        blockContainerType.create(null, paragraphType.create()),
                    );
                },
            }),
        ];
    },
});
