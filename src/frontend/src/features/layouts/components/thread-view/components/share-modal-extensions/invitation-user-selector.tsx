// FORK: reproduced from @gouvfr-lasuite/ui-kit InvitationUserSelectorList
// since the upstream component is not publicly exported. Preserves the
// upstream CSS classes (c__add-share-user-list, c__add-share-user-item)
// so the visual styling bundled in ui-kit's style.css applies as-is.
import { ReactNode, useState } from "react";
import { Button, useCunningham } from "@gouvfr-lasuite/cunningham-react";
import type { DropdownMenuOption, UserData } from "@gouvfr-lasuite/ui-kit";
import { AccessRoleDropdown } from "./access-role-dropdown";

export type InvitationUserSelectorListProps<UserType> = {
    users: UserData<UserType>[];
    onRemoveUser: (user: UserData<UserType>) => void;
    rightActions?: ReactNode;
    onShare: () => void;
    roles: DropdownMenuOption[];
    selectedRole: string;
    shareButtonLabel?: string;
    onSelectRole: (role: string) => void;
};

export const InvitationUserSelectorList = <UserType,>({
    users,
    onRemoveUser,
    rightActions,
    onShare,
    shareButtonLabel,
    roles,
    selectedRole,
    onSelectRole,
}: InvitationUserSelectorListProps<UserType>) => {
    const { t } = useCunningham();
    const [isOpen, setIsOpen] = useState(false);
    return (
        <div className="c__add-share-user-list" data-testid="selected-users-list">
            <div className="c__add-share-user-list__items">
                {users.map((user) => (
                    <InvitationUserSelectorItem
                        key={user.id}
                        user={user}
                        onRemoveUser={onRemoveUser}
                    />
                ))}
            </div>
            <div className="c__add-share-user-list__right-actions">
                {rightActions}
                <AccessRoleDropdown
                    roles={roles}
                    selectedRole={selectedRole}
                    onSelect={onSelectRole}
                    isOpen={isOpen}
                    onOpenChange={setIsOpen}
                    canDelete={false}
                    onDelete={undefined}
                />
                <Button onClick={onShare}>
                    {shareButtonLabel ?? t("components.share.shareButton")}
                </Button>
            </div>
        </div>
    );
};

type InvitationUserSelectorItemProps<UserType> = {
    user: UserData<UserType>;
    onRemoveUser: (user: UserData<UserType>) => void;
};

const InvitationUserSelectorItem = <UserType,>({
    user,
    onRemoveUser,
}: InvitationUserSelectorItemProps<UserType>) => {
    return (
        <div className="c__add-share-user-item" data-testid="selected-user-item">
            <span>{user.full_name || user.email}</span>
            <Button
                variant="tertiary"
                color="neutral"
                size="nano"
                onClick={() => onRemoveUser?.(user)}
                icon={<span className="material-icons">close</span>}
            />
        </div>
    );
};
