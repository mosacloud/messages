import { Icon, IconType } from "@gouvfr-lasuite/ui-kit";
import clsx from "clsx";
import { useId } from "react";

type BannerProps = {
    children: React.ReactNode;
    type: "info" | "error" | "warning";
    icon?: React.ReactNode;
    compact?: boolean;
    fullWidth?: boolean;
}

/**
 * A banner component that displays a message with an icon and a type (error or info).
 * TODO: Migrate this component into our ui-kit
 */
export const Banner = ({ children, type = 'info', icon, compact = false, fullWidth = false }: BannerProps) => {
    const ariaLabelId = useId();

    return (
        <div
            className={clsx("banner", `banner--${type}`, { "banner--compact": compact, "banner--full-width": fullWidth })}
            role="alert"
            aria-live="polite"
            data-testid="banner"
            aria-labelledby={ariaLabelId}
        >
            <div className="banner__content">
                <div
                    className="banner__content__icon"
                    aria-hidden="true"
                >
                    {
                        icon ? icon : (
                            <Icon name={type} type={IconType.OUTLINED} />
                        )
                    }
                </div>
                <div className="banner__content__text" id={ariaLabelId}>
                    {children}
                </div>
            </div>
        </div>
    );
}
