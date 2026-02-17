import { Mailbox, MessageTemplate, MessageTemplateTypeChoices, useMailboxesMessageTemplatesCreate, useMailboxesMessageTemplatesUpdate, getMailboxesMessageTemplatesListUrl } from "@/features/api/gen";
import { RhfInput } from "@/features/forms/components/react-hook-form/rhf-input";
import { RhfCheckbox } from "@/features/forms/components/react-hook-form/rhf-checkbox";
import { useMailboxContext } from "@/features/providers/mailbox";
import { zodResolver } from "@hookform/resolvers/zod";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";
import { FormProvider, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { SignatureComposer } from "@/features/signatures/components/signature-composer";
import { Base64ComposerHandle } from "@/features/blocknote/hooks/use-base64-composer";
import { addToast, ToasterItem } from "@/features/ui/components/toaster";
import i18n from "@/features/i18n/initI18n";
import { handle } from "@/features/utils/errors";

/**
 * Modal component to compose a signature for a mailbox.
 */
type ModalComposeMailboxSignatureProps = {
    isOpen: boolean;
    onClose: () => void;
    signature?: MessageTemplate;
}

export const ModalComposeMailboxSignature = ({ isOpen, onClose, signature }: ModalComposeMailboxSignatureProps) => {
    const { t } = useTranslation();
    const { selectedMailbox } = useMailboxContext();
    const queryClient = useQueryClient();

    if (!selectedMailbox) {
        return null;
    }

    const invalidateSignatures = async () => {
        await queryClient.invalidateQueries({ queryKey: [getMailboxesMessageTemplatesListUrl(selectedMailbox.id)], exact: false });
    }

    const handleSuccess = async () => {
        await invalidateSignatures();
        onClose();
        addToast(
            <ToasterItem type="info">
                <span>{
                    signature ? t("Signature updated!") : t("Signature created!")
                }</span>
            </ToasterItem>,
        );
    }

    return (
        <Modal
            isOpen={isOpen}
            title={signature ? t('Edit signature "{{signature}}"', { signature: signature.name }) : t("Create a new signature")}
            size={ModalSize.LARGE}
            onClose={onClose}
        >
            <div className="modal-compose-signature">
                <SignatureComposeForm mailbox={selectedMailbox} defaultValue={signature} onSuccess={handleSuccess} />
            </div>
        </Modal>
    );
};

type SignatureComposerFormProps = {
    mailbox: Mailbox;
    defaultValue?: MessageTemplate;
    onSuccess?: () => void;
}

const signatureComposerSchema = () => z.object({
    name: z.string().min(1, { error: i18n.t("Name is required") }),
    is_default: z.boolean(),
    rawBody: z.string().min(1, { error: i18n.t("Content is required") }),
});

type SignatureComposerFormData = z.infer<ReturnType<typeof signatureComposerSchema>>;

const SignatureComposeForm = ({ mailbox, defaultValue, onSuccess }: SignatureComposerFormProps) => {
    const { t } = useTranslation();
    const composerRef = useRef<Base64ComposerHandle>(null);
    const form = useForm<SignatureComposerFormData>({
        resolver: zodResolver(signatureComposerSchema()),
        defaultValues: {
            name: defaultValue?.name ?? "",
            is_default: defaultValue?.is_default ?? false,
            rawBody: defaultValue?.raw_body,
        }
    });
    const { mutateAsync: createSignature, isPending } = useMailboxesMessageTemplatesCreate();
    const { mutateAsync: updateSignature, isPending: isUpdating } = useMailboxesMessageTemplatesUpdate();
    const isSubmitting = isPending || isUpdating;

    const onSubmit = async (data: SignatureComposerFormData): Promise<void> => {
        const { htmlBody, textBody } = await composerRef.current!.exportContent();
        if (!textBody) {
            form.setError("rawBody", { message: t("Content is required") });
            return;
        }
        try {
            if (defaultValue?.id) {
                await updateSignature({
                    mailboxId: mailbox.id,
                    id: defaultValue.id,
                    data: {
                        name: data.name,
                        type: MessageTemplateTypeChoices.signature,
                        is_default: data.is_default,
                        html_body: htmlBody,
                        text_body: textBody,
                        raw_body: data.rawBody,
                    }
                });
            } else {
                await createSignature({
                    mailboxId: mailbox.id,
                    data: {
                        name: data.name,
                        type: MessageTemplateTypeChoices.signature,
                        is_default: data.is_default,
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
                    <span>{t("Failed to save signature. Please try again.")}</span>
                </ToasterItem>,
            );
            return;
        }
        onSuccess?.();
    }

    return (
        <FormProvider {...form}>
            <form className="signature-composer-form" onSubmit={form.handleSubmit(onSubmit)}>
                <div className="form-field-row">
                    <RhfInput
                        label={t('Name')}
                        name="name"
                        text={form.formState.errors.name?.message && t(form.formState.errors.name.message)}
                        fullWidth
                    />
                </div>
                <div className="form-field-row">
                    <SignatureComposer
                        ref={composerRef}
                        defaultValue={defaultValue?.raw_body}
                        state={form.formState.errors.rawBody?.message ? "error" : "default"}
                        text={form.formState.errors.rawBody?.message && t(form.formState.errors.rawBody.message)}
                        blockNoteOptions={{ autofocus: "end" }}
                    />
                </div>
                <div className="form-field-row">
                    <RhfCheckbox
                        label={t('Default signature')}
                        name="is_default"
                        text={t('The default signature will be automatically loaded when composing a new message.')}
                        fullWidth
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
