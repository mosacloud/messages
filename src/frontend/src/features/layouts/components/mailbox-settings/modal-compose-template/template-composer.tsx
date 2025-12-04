import { BlockNoteViewField } from "@/features/blocknote/blocknote-view-field";
import { BlockNoteSchema, defaultBlockSpecs, defaultInlineContentSpecs } from "@blocknote/core";
import { InlineTemplateVariable, TemplateVariableSelector } from "@/features/blocknote/inline-template-variable";
import * as locales from '@blocknote/core/locales';
import { useCreateBlockNote } from "@blocknote/react";
import { FieldProps } from "@gouvfr-lasuite/cunningham-react";
import { useEffect, useCallback } from "react";
import { useFormContext } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Toolbar } from "@/features/blocknote/toolbar";
import MailHelper from "@/features/utils/mail-helper";
import { BlockSignature, BlockSignatureConfigProps, SignatureTemplateSelector } from "@/features/blocknote/signature-block";
import { MessageTemplateTypeChoices, useMailboxesMessageTemplatesAvailableList, usePlaceholdersRetrieve } from "@/features/api/gen";
import { useMailboxContext } from "@/features/providers/mailbox";

const TEMPLATE_BLOCKNOTE_SCHEMA = BlockNoteSchema.create({
    blockSpecs: {
        ...defaultBlockSpecs,
        'signature': BlockSignature,
    },
    inlineContentSpecs: {
        ...defaultInlineContentSpecs,
        'template-variable': InlineTemplateVariable,
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
    const { selectedMailbox } = useMailboxContext();

    const { data: { data: placeholders = {} } = {}, isLoading: isLoadingPlaceholders } = usePlaceholdersRetrieve({
        query: {
            refetchOnMount: true,
            refetchOnWindowFocus: true,
        }
    });

    const { data: { data: activeSignatures = [] } = {}, isLoading: isLoadingSignatures } = useMailboxesMessageTemplatesAvailableList(
        selectedMailbox?.id || "",
        {
            type: MessageTemplateTypeChoices.signature,
        },
        {
            query: {
                enabled: !!selectedMailbox?.id,
                refetchOnMount: true,
                refetchOnWindowFocus: true,
            },
        }
    );

    const editor = useCreateBlockNote({
        schema: TEMPLATE_BLOCKNOTE_SCHEMA,
        tabBehavior: "prefer-navigate-ui",
        initialContent: defaultValue ? JSON.parse(defaultValue): [{ type: "paragraph", content: [{ type: "text", text: "", styles: {} }] }],
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

    const handleChange = useCallback(async () => {
        const markdown = await editor.blocksToMarkdownLossy(editor.document);
        const html = await MailHelper.markdownToHtml(markdown);
        form.setValue("rawBody", JSON.stringify(editor.document), { shouldDirty: true });
        form.setValue("textBody", markdown);
        form.setValue("htmlBody", html);

        // No need to update signatureId in form as it's only used for UI
    }, [editor, form]);

    useEffect(() => {
        if(!editor) return;

        // Detect current signature on mount
        const signatureBlock = editor.getBlock('signature');
        if (signatureBlock?.type === 'signature') {
            const templateId = signatureBlock.props.templateId;
            const signature = activeSignatures.find(s => s.id === templateId);
            if (signature) {
                // Update the signature selector
                editor.updateBlock(signatureBlock.id, {
                    type: 'signature',
                    props: {
                        templateId: signature.id,
                        mailboxId: selectedMailbox?.id,
                    }
                });
            }
        }

        handleChange();
    }, [editor, handleChange, activeSignatures, selectedMailbox?.id]);

    useEffect(() => {
        if (!editor || isLoadingSignatures) return;

        // Check if signature is already in the editor
        const signatureBlock = editor.getBlock('signature');
        if (signatureBlock) {
            // In case there is a signature block, we remove the block if :
            // - the templateId does not match an active signature
            const blockSignatureId = (signatureBlock.props as BlockSignatureConfigProps).templateId;
            const isSignatureStale = activeSignatures.findIndex(signature => signature.id === blockSignatureId) < 0;
            if (isSignatureStale) editor.removeBlocks(["signature"]);
            else return;
        }

        if (activeSignatures.length === 0) return;

        let signatureToUse = undefined;

        // Use in priority the forced signature block if it exists
        signatureToUse = activeSignatures.find(signature => signature.is_forced);

        // Add signature block if we have a signature to use
        if (signatureToUse) {
            // Add signature at the end of the document
            const signatureBlock = {
                id: "signature",
                type: "signature" as const,
                props: {
                    templateId: signatureToUse.id,
                    mailboxId: selectedMailbox?.id,
                }
            };

            // Insert at the end
            if (editor.document.length === 0) {
                editor.insertBlocks([{ type: "paragraph", content: [{ type: "text", text: "", styles: {} }] }], "", "after");
            }

            // Put signature at the end of the document
            // Insert signature at the end of the document
            editor.insertBlocks([signatureBlock], editor.document[editor.document.length - 1].id, "after");

        }
    }, [editor, isLoadingSignatures, activeSignatures, selectedMailbox?.id]);

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
                <Toolbar>
                    <SignatureTemplateSelector
                        templates={activeSignatures}
                        isLoading={isLoadingSignatures}
                        mailboxId={selectedMailbox?.id}
                    />
                    <TemplateVariableSelector
                        variables={placeholders}
                        isLoading={isLoadingPlaceholders}
                    />
                </Toolbar>
            </BlockNoteViewField>
            <input {...form.register("htmlBody")} type="hidden" />
            <input {...form.register("textBody")} type="hidden" />
            <input {...form.register("rawBody")} type="hidden" />
        </>
    )
};
