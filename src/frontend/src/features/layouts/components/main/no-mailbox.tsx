import { Button } from "@gouvfr-lasuite/cunningham-react"
import { logout } from "@/features/auth";
import { useTranslation } from "react-i18next";
import { Icon, IconSize, IconType } from "@gouvfr-lasuite/ui-kit";

export const NoMailbox = () => {
    const { t } = useTranslation();
    return (
        <div className="no-mailbox">
            <div>
                <Icon name="report" type={IconType.OUTLINED} size={IconSize.LARGE} aria-hidden="true" />
                <p>{t('No mailbox.')}</p>
                <Button onClick={logout}>{t('Logout')}</Button>
            </div>
        </div>
    )
}
