import { Mailbox, MessageTemplate, MessageTemplateTypeChoices, useMailboxesMessageTemplatesCreate, useMailboxesMessageTemplatesUpdate, getMailboxesMessageTemplatesListUrl } from "@/features/api/gen";
import { RhfInput } from "@/features/forms/components/react-hook-form/rhf-input";
import { useMailboxContext } from "@/features/providers/mailbox";
import { zodResolver } from "@hookform/resolvers/zod";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";
import { FormProvider, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { TemplateComposer } from "./template-composer";
import { Base64ComposerHandle } from "@/features/blocknote/hooks/use-base64-composer";
import { addToast, ToasterItem } from "@/features/ui/components/toaster";
import i18n from "@/features/i18n/initI18n";
import { handle } from "@/features/utils/errors";

/**
 * Modal component to compose a template for a mailbox.
 */
type ModalComposeTemplateProps = {
    isOpen: boolean;
    onClose: () => void;
    template?: MessageTemplate;
}

export const ModalComposeTemplate = ({ isOpen, onClose, template }: ModalComposeTemplateProps) => {
    const { t } = useTranslation();
    const { selectedMailbox } = useMailboxContext();
    const queryClient = useQueryClient();
    const invalidateMessageTemplates = async () => {
        await queryClient.invalidateQueries({ queryKey: [getMailboxesMessageTemplatesListUrl(selectedMailbox!.id)], exact: false });
    }

    const handleSuccess = async () => {
        await invalidateMessageTemplates();
        onClose();
        addToast(
            <ToasterItem type="info">
                <span>{
                    template ? t("Template updated!") : t("Template created!")
                }</span>
            </ToasterItem>,
        );
    }

    return (
        <Modal
            isOpen={isOpen}
            title={template ? t('Edit template "{{template}}"', { template: template.name }) : t("Create a new template")}
            size={ModalSize.LARGE}
            onClose={onClose}
        >
            <div className="modal-compose-template">
                <TemplateComposeForm mailbox={selectedMailbox!} defaultValue={template} onSuccess={handleSuccess} />
            </div>
        </Modal>
    );
};

type TemplateComposerFormProps = {
    mailbox: Mailbox;
    defaultValue?: MessageTemplate;
    onSuccess?: () => void;
}

const templateComposerSchema = () => z.object({
    name: z.string().min(1, { error: i18n.t("Name is required") }),
    rawBody: z.string().min(1, { error: i18n.t("Content is required") }),
});

type TemplateComposerFormData = z.infer<ReturnType<typeof templateComposerSchema>>;

const TemplateComposeForm = ({ mailbox, defaultValue, onSuccess }: TemplateComposerFormProps) => {
    const { t } = useTranslation();
    const composerRef = useRef<Base64ComposerHandle>(null);
    const form = useForm<TemplateComposerFormData>({
        resolver: zodResolver(templateComposerSchema()),
        defaultValues: {
            name: defaultValue?.name ?? "",
            rawBody: defaultValue?.raw_body ?? undefined,
        }
    });
    const { mutateAsync: createTemplate, isPending } = useMailboxesMessageTemplatesCreate();
    const { mutateAsync: updateTemplate, isPending: isUpdating } = useMailboxesMessageTemplatesUpdate();
    const isSubmitting = isPending || isUpdating;

    const onSubmit = async (data: TemplateComposerFormData): Promise<void> => {
        const { htmlBody, textBody } = await composerRef.current!.exportContent();
        if (!textBody) {
            form.setError("rawBody", { message: t("Content is required") });
            return;
        }

        try {
            if (defaultValue?.id) {
                await updateTemplate({
                    mailboxId: mailbox.id,
                    id: defaultValue.id,
                    data: {
                        name: data.name,
                        type: MessageTemplateTypeChoices.message,
                        html_body: htmlBody,
                        text_body: textBody,
                        raw_body: data.rawBody,
                    }
                });
            } else {
                await createTemplate({
                    mailboxId: mailbox.id,
                    data: {
                        name: data.name,
                        type: MessageTemplateTypeChoices.message,
                        html_body: htmlBody,
                        text_body: textBody,
                        raw_body: data.rawBody,
                    }
                });
            }
        } catch (error) {
            handle(error);
            addToast(
                <ToasterItem type="error">
                    <span>{t("Failed to save template. Please try again.")}</span>
                </ToasterItem>,
            );
            return;
        }
        onSuccess?.();
    }

    return (
        <FormProvider {...form}>
            <form className="template-composer-form" onSubmit={form.handleSubmit(onSubmit)}>
                <div className="form-field-row">
                    <RhfInput
                        label={t('Name')}
                        name="name"
                        text={form.formState.errors.name?.message && t(form.formState.errors.name.message)}
                        fullWidth
                    />
                </div>
                <div className="form-field-row">
                    <TemplateComposer
                        ref={composerRef}
                        defaultValue={defaultValue?.raw_body}
                        state={form.formState.errors.rawBody?.message ? "error" : "default"}
                        text={form.formState.errors.rawBody?.message && t(form.formState.errors.rawBody.message)}
                        blockNoteOptions={{ autofocus: "end" }}
                    />
                </div>
                <div className="form-actions">
                    <Button type="submit" disabled={isSubmitting}>
                        {isSubmitting ? t('Saving...') : t('Save')}
                    </Button>
                </div>
            </form>
        </FormProvider>
    );
};
