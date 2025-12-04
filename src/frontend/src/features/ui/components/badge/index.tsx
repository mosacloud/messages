import clsx from "clsx"
import { HTMLAttributes, PropsWithChildren } from "react"

type BadgeProps = PropsWithChildren<HTMLAttributes<HTMLDivElement>> & {
    color?: 'brand' | 'neutral';
    variant?: 'primary' | 'secondary' | 'tertiary';
}


export const Badge = ({ children, className, color = 'brand', variant = 'primary', ...props }: BadgeProps) => {
    return (
        <div className={clsx("badge", `badge--${color}`, `badge--${variant}`, className, )} {...props}>
            {children}
        </div>
    )
}
