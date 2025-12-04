import { Button } from "@gouvfr-lasuite/cunningham-react";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import { useTranslation } from "react-i18next";
import { useModal } from "@gouvfr-lasuite/cunningham-react";
import { ModalComposeTemplate } from "../modal-compose-template";

export const ComposeTemplateAction = () => {
    const { t } = useTranslation();
    const modal = useModal();

    return (
        <>
            <Button
                onClick={() => modal.open()}
                icon={<Icon name="add" />}
            >
                {t("New template")}
            </Button>
            <ModalComposeTemplate
                isOpen={modal.isOpen}
                onClose={() => modal.close()}
            />
        </>
    );
};
