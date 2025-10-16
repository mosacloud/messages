import { BlockNoteViewField } from "@/features/blocknote/blocknote-view-field";
import { BlockNoteSchema, defaultInlineContentSpecs } from "@blocknote/core";
import * as locales from '@blocknote/core/locales';
import { useCreateBlockNote } from "@blocknote/react";
import { FieldProps } from "@openfun/cunningham-react";
import { useEffect } from "react";
import { useFormContext } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Toolbar } from "@/features/blocknote/toolbar";
import MailHelper from "@/features/utils/mail-helper";

const TEMPLATE_BLOCKNOTE_SCHEMA = BlockNoteSchema.create({
    inlineContentSpecs: {
        ...defaultInlineContentSpecs,
    }
});

export type TemplateComposerBlockNoteSchema = typeof TEMPLATE_BLOCKNOTE_SCHEMA;
export type TemplateComposerBlockSchema = TemplateComposerBlockNoteSchema['blockSchema'];
export type TemplateComposerInlineContentSchema = TemplateComposerBlockNoteSchema['inlineContentSchema'];
export type TemplateComposerStyleSchema = TemplateComposerBlockNoteSchema['styleSchema'];

type TemplateComposerProps = FieldProps & {
    blockNoteOptions?: Partial<typeof TEMPLATE_BLOCKNOTE_SCHEMA>
    defaultValue?: string | null;
    disabled?: boolean;
}

/**
 * The composer component for the template content.
 */
export const TemplateComposer = ({ blockNoteOptions, defaultValue, disabled = false, ...props }: TemplateComposerProps) => {
    const { t, i18n } = useTranslation();
    const form = useFormContext();

    const editor = useCreateBlockNote({
        schema: TEMPLATE_BLOCKNOTE_SCHEMA,
        tabBehavior: "prefer-navigate-ui",
        initialContent: defaultValue ? JSON.parse(defaultValue): [{ type: "paragraph", content: "" }],
        trailingBlock: false,
        dictionary: {
            ...(locales[(i18n.resolvedLanguage) as keyof typeof locales] || locales.en),
            placeholders: {
                ...(locales[(i18n.resolvedLanguage) as keyof typeof locales] || locales.en).placeholders,
                emptyDocument: t('Start typing...'),
                default: t('Start typing...'),
            }
        },
        ...blockNoteOptions,
    }, [i18n.resolvedLanguage]);

    const handleChange = async () => {
        const markdown = await editor.blocksToMarkdownLossy(editor.document);
        const html = await MailHelper.markdownToHtml(markdown);
        form.setValue("rawBody", JSON.stringify(editor.document), { shouldDirty: true });
        form.setValue("textBody", markdown);
        form.setValue("htmlBody", html);
    }

    useEffect(() => {
        if(!editor) return;
        handleChange();
    }, [editor])

    return (
        <>
            <BlockNoteViewField
                {...props}
                className="template-composer"
                fullWidth
                disabled={disabled}
                composerProps={{
                    editor,
                    onChange: handleChange,
                }}
            >
                <Toolbar />
            </BlockNoteViewField>
            <input {...form.register("htmlBody")} type="hidden" />
            <input {...form.register("textBody")} type="hidden" />
            <input {...form.register("rawBody")} type="hidden" />
        </>
    )
};
