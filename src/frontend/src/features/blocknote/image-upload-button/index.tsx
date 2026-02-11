import { useBlockNoteEditor, useComponentsContext, useEditorState } from "@blocknote/react";
import { useTranslation } from "react-i18next";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";
import { MessageComposerBlockSchema, MessageComposerInlineContentSchema, MessageComposerStyleSchema } from "@/features/forms/components/message-composer";

export const ImageUploadButton = () => {
    const { t } = useTranslation();
    const editor = useBlockNoteEditor<MessageComposerBlockSchema, MessageComposerInlineContentSchema, MessageComposerStyleSchema>();
    const Components = useComponentsContext()!;

    const hasInlineContent = useEditorState({
        editor,
        selector: ({ editor }) => {
            const selectedBlocks = editor.getSelection()?.blocks || [
                editor.getTextCursorPosition().block,
            ];
            return selectedBlocks.some((block) => block.content !== undefined);
        },
    });

    if (!hasInlineContent) return null;

    const handleClick = () => {
        const currentBlock = editor.getTextCursorPosition().block;
        const insertedBlocks = editor.insertBlocks(
            [{ type: "image" }],
            currentBlock,
            "after",
        );
        const filePanel = editor.getExtension("filePanel") as { showMenu: (blockId: string) => void } | undefined;
        filePanel?.showMenu(insertedBlocks[0].id);
    };

    return (
        <Components.FormattingToolbar.Button
            icon={<Icon name="image" size={IconSize.SMALL} />}
            label={t("Insert image")}
            mainTooltip={t("Insert image")}
            onClick={handleClick}
        />
    );
};
