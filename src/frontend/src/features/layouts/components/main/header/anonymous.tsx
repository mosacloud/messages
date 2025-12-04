import { HeaderProps, Icon, useResponsive } from "@gouvfr-lasuite/ui-kit";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useTranslation } from "react-i18next";
import { LanguagePicker } from "../language-picker";
import { LagaufreButton } from "@/features/ui/components/lagaufre";


export const AnonymousHeader = ({
  leftIcon,
  onTogglePanel,
  isPanelOpen,
}: HeaderProps) => {
  const { t } = useTranslation();
  const { isDesktop } = useResponsive();

  return (
    <div className="c__header c__header--anonymous">
      <div className="c__header__toggle-menu">
        <Button
          size="medium"
          onClick={onTogglePanel}
          aria-label={isPanelOpen ? t("Close the menu") : t("Open the menu")}
          color="brand"
          variant="tertiary"
          icon={<Icon name={isPanelOpen ? "close" : "menu"} />}
        />
      </div>
      <div className="c__header__left">
        {leftIcon}
      </div>
      <div className="c__header__right">
        {isDesktop && (
          <>
            <LanguagePicker />
            <LagaufreButton />
          </>
        )}

      </div>
    </div>
  );
};
