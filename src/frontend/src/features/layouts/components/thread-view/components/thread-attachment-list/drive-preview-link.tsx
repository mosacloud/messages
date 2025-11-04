import { DriveIcon } from "@/features/forms/components/message-form/drive-icon";
import { useConfig } from "@/features/providers/config";
import { Button } from "@openfun/cunningham-react";
import { useTranslation } from "react-i18next";

type DrivePreviewLinkProps = {
    fileId: string;
}

/**
 * DrivePreviewLink
 * A component which renders a link to open the Drive preview of a file.
 * https://drive.instance/explorer/items/files/:itemId
 */
export const DrivePreviewLink = ({ fileId }: DrivePreviewLinkProps) => {
    const { DRIVE } = useConfig();
    const { t } = useTranslation();

    if (!DRIVE) return null;

    return (
        <Button
            aria-label={t("Open Drive preview")}
            title={t("Open Drive preview")}
            href={`${DRIVE.file_url}/${fileId}`}
            target="_blank"
            size="medium"
            color="tertiary-text"
            icon={<DriveIcon />}
        />
    )
}
